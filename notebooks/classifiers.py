# classification models and choice-sets for categorizing docs
from laya import Router


# question sets by report type
section_choices = {
    "front_matter": "Front  Matter -- cover page, table of contents, forward-looking statements",
    "business": "Business -- company overview, products, competition, regulation, employees",
    "risk_factors": "Risk Factors -- risks facing the company",
    "cybersecurity": "Cybersecurity -- cyber risk management and governance",
    "properties": "Properties -- facilities and real estate",
    "legal_proceedings": "Legal Proceedings -- litigation and legal matters",
    "equity_and_repurchases": "Equity and Repurchases -- stock market info, dividends, buybacks",
    "mdna": "MD&A -- management's discussion of results and liquidity",
    "market_risk": "Market Risk -- interest rate, FX, commodity risk disclosures",
    "financial_statements": "Financial Statements -- balance sheet, income statement, cash flows",
    "notes_to_financial_statements": "Notes to Financial Statements -- accounting policies and note disclosures",
    "auditors_report": "Auditor's Report -- independent auditor's opinion",
    "controls_and_accountants": "Controls and Accountants -- internal controls, auditor changes",
    "governance_and_management": "Governance and Management -- directors, officers, related transactions",
    "compensation_and_ownership": "Compensation and Ownership -- executive pay, beneficial ownership",
    "exhibits_and_schedules": "Exhibits and Schedules -- exhibit index, financial statement schedules",
    # "signatures": "Signatures -- signature pages, power of attorney",
    "material_events": "Material Events -- significant events affecting the company; deals, financing, impairments, bankruptcy",
    "short_or_na_items": "Short or N/A Items -- 'None' or 'Not applicable' items",
    "other": "Other -- anything else",
}

# specifies choice sets by report type -- 10K has most sections, 10Q and 8K are mostly subsets of it
section_questions = {
    "10-K": {'sections': {  # 'sections' is arbitrary, but laya expects a top-level key for the question set
        "type": "choice",
        "instructions": "Which part of the 10-K does this text belong to?",
        "criteria": {
            c: section_choices[c] for c in section_choices 
            if c not in ('material_events')
    }}},
    "10-Q": {'sections': {
        "type": "choice",
        "instructions": "Which part of the 10-Q does this text belong to?",
        "criteria": {
            c: section_choices[c] for c in section_choices 
            if c not in ('governance_and_management', 'compensation_and_ownership', 'material_events')
    }}},
    "8-K": {'sections': {
        "type": "choice",
        "instructions": "Which part of the 8-K does this text belong to?",
        "criteria": {
            c: section_choices[c] for c in section_choices 
            if c not in ('legal_proceedings', 'market_risk', 'notes_to_financial_statements', 
                         'auditors_report', 'compensation_and_ownership', 'short_or_na_items')
    }}}
}



def score_sections(filing, laya_instance = None, max_len: int | None = None):
    """Attribute each section in filing to a section label using Laya, 
    optionally truncating text to max_len characters
    """
    if laya_instance is None:
        laya_instance = Router()
    sections = filing.obj().sections
    results = {}
    for s in sections:
        # first few lines of a section typically reveal the category -- so truncation can be efficient
        if max_len is not None:
            text = sections.get(s).text()[:max_len]
        else:
            text = sections.get(s).text()
        res = laya_instance.predict(state=text, questions=section_questions[filing.form])  # limit choices relevant to filing's form type
        results[s] = {
            "pred": res["answers"]["sections"]["choice"],
            "confidence": res["answers"]["sections"]["answer_confidence"],
            "response": res,
            "header": text[:60],
            "text": text,
        }
    return results
