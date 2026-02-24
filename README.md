# EquiBot
This is a **very early WIP project**.

EquiBot is a general-purpose suite of equity research tools intended to be publicly accessible and fully local (if you want/have the hardware).
Includes agentic workflows for financial analysis, local equity and financial data management, portfolio analysis, and more.

All data used is, and will be, from publicly available sources and fully maintainable on local hardware.\
LLM calls are managed by Openrouter for remotely hosted LLMs, but could be replaced with local LLMs.\
The only API dependencies are, therefore, an email handle for the SEC's API, and an Openrouter API key if you choose to use Openrouter.

# Current Content
### Earnings Analytics
I'm currently focused on refining agentic processes for analyzing earnings reports.\
The `reporting.py` script builds out a simple agent workflow to synthesize structured and unstructured data from earnings reports filed with the SEC along with earnings call transcripts into cogent executive summaries.

# TODO
### Earnings Analytics
- Develop a strictly-typed equity profiles to enable stateful investment thesis development over multiple earnings periods
- Set-up lightweight, local storage system to manage financial report data, archive earnings documents, and archive LLM produced synopses


