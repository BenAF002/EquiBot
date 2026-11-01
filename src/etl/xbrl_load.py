"""Load one filing's XBRL into the raw layer.

Four things come out of an edgartools XBRL object, matching the four parts of the format:

    facts              -> raw.xbrl_facts              (the instance document)
    concept metadata   -> raw.xbrl_concepts           (schema + label linkbase)
    presentation arcs  -> raw.xbrl_roles + raw.xbrl_presentation_arcs
    calculation arcs   -> raw.xbrl_roles + raw.xbrl_calculation_arcs

Nothing here classifies or interprets. Classification happens in db/transforms/*.sql.

load_xbrl() REPLACES everything stored for the filing. Rows for one filing all come from
one source document, so delete-then-insert at filing grain is the correct idempotent
operation: a row-level ON CONFLICT upsert would leave behind rows that a newer parser
version no longer emits. The caller owns the transaction.
"""
from decimal import Decimal, InvalidOperation
from psycopg.types.json import Jsonb

from . import helpers as h


# ---------------------------------------------------------------- extraction (no database)
def extract_facts(xbrl, filing_id):
    """Undimensioned facts as insert tuples, plus counts of skipped and conflicting rows."""
    df = xbrl.query().by_dimension(None).to_dataframe()

    rows, conflicts, skipped = {}, [], []
    for r in df.to_dict("records"):
        # Instants fill period_instant and leave period_end NaN; durations the reverse.
        # (NaN is truthy, so `period_end or period_instant` would pick the NaN.)
        instant = h.clean_date(r.get("period_instant"))
        if instant is not None:
            start, end = None, instant
        else:
            start, end = h.clean_date(r.get("period_start")), h.clean_date(r.get("period_end"))
        raw_value = h.clean(r.get("value"))
        if end is None or raw_value is None or str(raw_value).strip() == "":
            skipped.append(r)
            continue

        # XBRL rule: numeric facts carry a unit, non-numeric facts do not.
        unit = h.clean(r.get("unit_ref"))
        num, text = None, None
        if unit is not None:
            try:
                d = Decimal(str(raw_value).strip())
                num = d if d.is_finite() else None
            except InvalidOperation:
                pass
        if num is None:
            text = str(raw_value)

        decimals = h.clean(r.get("decimals"))
        # row layout: (filing_id, concept, start, end, dimensions, unit, decimals, num, text)
        key = (h.norm_concept(r["concept"]), start, end, unit)
        if key in rows:
            if rows[key][7:9] != (num, text):
                conflicts.append(key)  # same identity, different value: keep the first, report
            continue
        rows[key] = (filing_id, key[0], start, end, Jsonb({}), unit,
                     None if decimals is None else str(decimals), num, text)
    return list(rows.values()), skipped, conflicts


def extract_structure(xbrl, filing_id):
    """Roles and arcs. Returns (roles, presentation_arcs, calculation_arcs)."""
    roles = {}
    pres, calc = {}, {}

    for role_uri, tree in xbrl.presentation_trees.items():
        roles[role_uri] = (filing_id, role_uri, tree.definition)
        # A node's children list holds every arc leaving it, in order, including a concept
        # listed twice under one parent (cash roll-forward). child_preferred_labels is
        # aligned with it by position. node.order and node.depth are NOT per-arc (they keep
        # the last occurrence only), so position comes from the list index instead.
        for node in tree.all_nodes.values():
            labels = node.child_preferred_labels or [None] * len(node.children)
            for pos, (child, label_role) in enumerate(zip(node.children, labels), start=1):
                pres[(role_uri, h.norm_concept(node.element_id), pos)] = (
                    filing_id, 
                    role_uri, 
                    h.norm_concept(node.element_id),
                    h.norm_concept(child), 
                    pos, 
                    label_role
                )

    for role_uri, tree in xbrl.calculation_trees.items():
        roles.setdefault(role_uri, (filing_id, role_uri, tree.definition))
        for arc in tree.all_arcs:
            key = (role_uri, h.norm_concept(arc.parent_id), h.norm_concept(arc.child_id))
            calc[key] = (filing_id, *key, Decimal(str(arc.weight)), Decimal(str(arc.order)))

    return list(roles.values()), list(pres.values()), list(calc.values())


def extract_concepts(xbrl, filing_id, concept_ids):
    """One row per concept. us-gaap/dei concepts are not in the filing's own schema, so
    balance and data_type are NULL for them; their labels come from the label linkbase."""
    catalog = {h.norm_concept(k): v for k, v in xbrl.element_catalog.items()}
    rows = []
    for concept in sorted(set(concept_ids) | set(catalog)):
        e = catalog.get(concept)
        local_name = concept.split(":", 1)[-1]
        rows.append((
            filing_id, concept,
            getattr(e, "period_type", None),
            getattr(e, "balance", None),
            getattr(e, "data_type", None) or None,
            # edgartools reports is_abstract=False for us-gaap headings (verified), so also
            # use the naming convention: headings end in 'Abstract'.
            bool(getattr(e, "abstract", False)) or local_name.endswith("Abstract"),
            Jsonb(dict(e.labels) if e is not None else {}),
        ))
    return rows


# ---------------------------------------------------------------- load
def load_xbrl(conn, xbrl, filing_id) -> dict:
    """Load XBRL data into the database.

    Returns a dictionary summarizing the number of roles, presentation arcs,
    calculation arcs, concepts, facts, and conflicts processed.
    """
    facts, skipped, conflicts = extract_facts(xbrl, filing_id)
    roles, pres, calc = extract_structure(xbrl, filing_id)
    concept_ids = ({f[1] for f in facts}
                   | {p[2] for p in pres} | {p[3] for p in pres}
                   | {c[2] for c in calc} | {c[3] for c in calc})
    concepts = extract_concepts(xbrl, filing_id, concept_ids)

    cur = conn.cursor()
    # children before parents (arcs reference roles)
    for table in ("xbrl_calculation_arcs", "xbrl_presentation_arcs", "xbrl_roles",
                  "xbrl_concepts", "xbrl_facts"):
        cur.execute(f"DELETE FROM raw.{table} WHERE filing_id = %s", (filing_id,))

    cur.executemany("INSERT INTO raw.xbrl_roles (filing_id, role_uri, definition) "
                    "VALUES (%s, %s, %s)", roles)
    cur.executemany("INSERT INTO raw.xbrl_presentation_arcs (filing_id, role_uri, parent_concept, "
                    "child_concept, position, preferred_label_role) VALUES (%s,%s,%s,%s,%s,%s)", pres)
    cur.executemany("INSERT INTO raw.xbrl_calculation_arcs (filing_id, role_uri, parent_concept, "
                    "child_concept, weight, arc_order) VALUES (%s,%s,%s,%s,%s,%s)", calc)
    cur.executemany("INSERT INTO raw.xbrl_concepts (filing_id, concept, period_type, balance, "
                    "data_type, is_abstract, labels) VALUES (%s,%s,%s,%s,%s,%s,%s)", concepts)
    cur.executemany("INSERT INTO raw.xbrl_facts (filing_id, concept, period_start, period_end, "
                    "dimensions, unit, decimals, value_num, value_text) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", facts)

    if skipped:
        print(f"  xbrl: skipped {len(skipped)} facts with no period or no value")
    if conflicts:
        print(f"  xbrl: {len(conflicts)} facts shared an identity but differed in value "
              f"(kept the first): {conflicts[:3]}")
    return {"roles": len(roles), "presentation_arcs": len(pres), "calculation_arcs": len(calc),
            "concepts": len(concepts), "facts": len(facts), "conflicts": len(conflicts),
            "skipped": skipped}