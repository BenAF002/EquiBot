###########################################
# Agents for processing financial reports #
###########################################

import os
from dotenv import load_dotenv
import re
import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Literal
from pydantic_ai import RunContext
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from edgar.company_reports.ten_k import TenK
from equibot.parsers.transcript import TranscriptScraper
from equibot.config import settings


####################
# Helper Functions #
####################

def get_statement_jsons(tenk):
    """Return compact, line-separated JSONs of each financial statemtent"""
    statements = [tenk.income_statement, tenk.balance_sheet, tenk.cash_flow_statement]
    res = {}
    for statement in statements:
        df = statement.to_dataframe()
        cols = [c for c in df.columns if c in ['label', 'standard_concept'] or c[:4].isnumeric()]
        df = df.loc[:, cols]  # truncate to minimum necessary columns
        res[statement.canonical_type] = df.to_json(orient='records', lines=True)
    return res


###########################
# Structured Dependencies #
###########################

@dataclass
class TenKDeps:
    """Dependencies for TenK sub-agents"""
    company_name: str
    ticker: str
    item_number: Optional[str]
    document_name: str
    document_content: str

@dataclass
class SynthDeps:
    """Dependencies for synthesizer agent"""
    company_name: str 
    ticker: str
    document_summaries: dict

@dataclass
class AuditorDeps:
    document: str  # document to verify
    company_name: str
    ticker: str
    form: Literal["10-K", "10-Q", "8-K"]
    income_statement: str
    cash_flow_statement: str
    balance_sheet: str


##########################
# Report-Specific Agents #
##########################

class TenKAgentFactory:
    def __init__(self, model_name: str):
        """
        Factory to create specialized agents for different Ten-K items
        Args:
            model_name: Name of the language model to use (e.g., 'openai/gpt-oss-120b')
        """
        self.model = OpenRouterModel(
            model_name,
            provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
        )

    def create_sub_agent(self) -> Agent:
        """Creates specialized sub-agent for a specific Ten-K item"""
        agent = Agent(
            self.model,
            output_type=str,
            deps_type=TenKDeps,
        )

        @agent.system_prompt
        def generate_prompt(ctx: RunContext[TenKDeps]) -> str:
            """Generates dynamic system prompt based on the document being analyzed"""
            item_info = f" (Item {ctx.deps.item_number})" if ctx.deps.item_number else ""
            return (
                f"You are an equity research analyst analyzing {ctx.deps.company_name}'s SEC 10-K filing. "
                f"Your task is to summarize the content of {ctx.deps.document_name}{item_info}. "
                "Focus on extracting key insights relevant for investment decisions, such as risks, financial performance, and strategic initiatives. "
                "Provide a concise summary that highlights the most important information from the document."
                f"----- DOCUMENT CONTENT -----\n"
                f"{ctx.deps.document_content}\n"
            )

        return agent
    

class TenKAgent:
    """
    Agent wrapper for 10-K analyses
    """
    def __init__(self, tenk: TenK, ticker: str,
                 synthesis_model: str = 'z-ai/glm-5', 
                 summary_model: str = 'openai/gpt-oss-120b'):
        self.tenk = tenk
        self.ticker = ticker
        self.synthesis_model = synthesis_model
        self.summary_model = summary_model

        # synthesis agent combines summaries into a cogent executive summary
        self.synth_agent = Agent(
            model=OpenRouterModel(
                self.synthesis_model,
                provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
            ),
            output_type=str,
            deps_type=SynthDeps,
        )

        @self.synth_agent.system_prompt
        def get_summaries(ctx: RunContext[SynthDeps]) -> str:
            summary_text = "\n".join(
                f"----- {doc_name.replace('_', ' ').title()} Summary -----\n{summary_response['output'].output}\n" 
                for doc_name, summary_response in ctx.deps.document_summaries.items()
            )
            return (
                f"You are a senior equity research analyst synthesizing insights from multiple documents about {ctx.deps.company_name}. "
                "Based on the following summaries of key documents, provide an integrated analysis that highlights the most critical insights for an investor. "
                "Focus on how the information from different documents interrelates and what it implies about the company's prospects.\n"
                f"{summary_text}"
            )
        
        # auditor compares metrics cited in the synthesized executive summary against financial statements
        self.auditor = Agent(
            model=OpenRouterModel(
                self.synthesis_model,
                provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
            ),
            output_type=str,
            deps_type=AuditorDeps,
            system_prompt=(
                """
                You are a financial auditor tasked with verifying the accuracy of
                numbers cited in a financial analysis document. You have access to three
                key financial statements presented in line-separated JSON formats.
                You may use these files to tie-out numbers cited in the document.
                When presenting verifications, always cite specific financial statements
                and line-item labels. 
                Unless otherwise requested, only identify numbers from the document that
                disagree with the financial statements or that are absent from the 
                financial statements.
                """
            )
        )

        @self.auditor.system_prompt
        def get_document(ctx: RunContext[AuditorDeps]) -> str:
            return ctx.deps.document

        @self.auditor.system_prompt
        def get_statements(ctx: RunContext[AuditorDeps]) -> str:
            return (
                f"""
                ---- Income Statement ---- \n{ctx.deps.income_statement}\n
                ---- Balance Sheet ---- \n{ctx.deps.balance_sheet}\n
                ---- Statement of Cash Flows ---- \n{ctx.deps.cash_flow_statement}\n
                """
            )

    def _init_tenk_agents(self, 
                         tenk: TenK | None = None, 
                         ticker: str | None = None, 
                         model_name: str | None = None):
        """
        Initialize agents for analysis of Ten-K documents
        Args:
            tenk: TenK edgartools object for selected 10-K earnings report
            ticker: company stock ticker for earnings-call transcript retrieval
            model_name: name of LLM to use
        """
        tenk = self.tenk if tenk is None else tenk
        ticker = self.ticker if ticker is None else ticker
        model_name = self.summary_model if model_name is None else model_name

        primary_items = ['business', 'risk_factors', 'management_discussion']
        documents = {item: tenk.__getattribute__(item) for item in primary_items}
        
        try:
            ec_scraper = TranscriptScraper(ticker=ticker)
            ec_year = tenk.period_of_report[:4]  # extract year from tenk obj
            transcript_data = ec_scraper.get_transcript(quarter=4, year=ec_year)
            transcript = "\n".join([
                f"{chunk['speaker']}, {chunk['title']} [{chunk['time']}]\n"
                + chunk['text'] + "\n"
                for chunk in transcript_data
            ])
            documents['earnings_call_transcript'] = transcript
        except Exception as e:
            print(f"No transcript retrieved. Error raised: {e}")

        factory = TenKAgentFactory(model_name=model_name)
        self.sub_agents = {}
        for item, content in documents.items():
            self.sub_agents[item] = factory.create_sub_agent()

        return self.sub_agents, documents


    async def _agent_run(self, 
                        agent: Agent, 
                        deps: TenKDeps, 
                        prompt: str = "Summarize the document") -> dict[str]:
        """Helper function to run agent asynchronously and time the execution"""
        start = time.time()
        res = await agent.run(prompt, deps=deps)
        res = {
            "agent_specialty": deps.document_name,
            "output": res,
            "execution_time": time.time() - start
        }
        return res

        
    async def struct_output(self, 
                         tenk: TenK | None = None, 
                         ticker: str | None = None, 
                         model_name: str | None = None) -> dict[dict]:
        """
        Run all agents asynchronously
        Args:
            tenk: TenK edgartools object for selected 10-K earnings report
            ticker: company stock ticker for earnings-call transcript retrieval
            model_name: name of LLM to use
        """
        tenk = self.tenk if tenk is None else tenk
        ticker = self.ticker if ticker is None else ticker
        model_name = self.summary_model if model_name is None else model_name

        agents, documents = self._init_tenk_agents(tenk, ticker, model_name)

        for doc_name, doc_content in documents.items():
            item_number = re.search(r'ITEM \d+', doc_content)
            item_number = item_number.group(0) if item_number else None
            dep = TenKDeps(
                company_name=tenk.company,
                ticker=ticker,
                item_number=item_number,
                document_name=doc_name,
                document_content=doc_content
            )
            documents[doc_name] = [doc_content, dep]

        results = await asyncio.gather(
            *[
                self._agent_run(
                    agents[item],            # assign to sub-agent
                    deps=documents[item][1]  # pass TenKDeps object for the document
                ) for item in documents.keys()
            ]
        )

        self.summaries_dict = {
            res["agent_specialty"]: {"output": res['output'], "execution_time": res['execution_time']} 
            for res in results
        }

        return self.summaries_dict


    async def synthesize(self):
        """Synthesize summaries of all 10-K documents an earnings calls into investment thesis"""
        summaries_dict = getattr(self, "summaries_dict", await self.struct_output())
        self.executive_summary = await self.synth_agent.run(
            "Synthesize the insights from the document summaries into a cohesive analysis.",
            deps=SynthDeps(self.tenk.company, self.ticker, summaries_dict)
        )
        return self.executive_summary
        
    
    async def audit(self, document: str | None = None):
        """
        Audit document using key financial statements
        Args:
            document: Document to audit - defaults to executive_summary if None
        """
        if document is None:
            assert hasattr(self, "executive_summary"), "Executive summary has not been synthesized. Either call .synthesize() or provide document"
            document = self.executive_summary
        
        statements = get_statement_jsons(self.tenk)

        self.audit_res = await self.auditor.run(
            user_prompt="verify the accuracy of the numbers cited in the document",
            deps=AuditorDeps(
                document=document,
                company_name=self.tenk.company,
                ticker=self.ticker,
                form=self.tenk.form,
                income_statement=statements['IncomeStatement'],
                balance_sheet=statements['BalanceSheet'],
                cash_flow_statement=statements['CashFlowStatement']
            )
        )

        return self.audit_res