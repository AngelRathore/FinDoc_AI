"""
Financial tools used by the LangGraph agent.
"""
import math
import re
from langchain.tools import tool


# ── Tool 1: Vector store retrieval ────────────────────────────────────────────
@tool
def search_documents(query: str) -> str:
    """Disabled legacy agent tool; document retrieval requires an authenticated owner scope."""
    return "Use the authenticated document chat endpoint to search private documents."


# ── Tool 2: DuckDuckGo web search ─────────────────────────────────────────────
@tool
def web_search(query: str) -> str:
    """Search the web for latest financial news and data."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=4))
        if not results:
            return "No web results found."
        formatted = []
        for r in results:
            formatted.append(f"Title: {r.get('title','')}\n{r.get('body','')}\nURL: {r.get('href','')}")
        return "\n\n---\n\n".join(formatted)
    except Exception as e:
        return f"Web search failed: {str(e)}"


# ── Tool 3: Stock price lookup ────────────────────────────────────────────────
@tool
def get_stock_price(ticker: str) -> str:
    """Get the current stock price and basic info for a ticker symbol (e.g. AAPL, RELIANCE.NS, TCS.NS)."""
    try:
        import yfinance as yf
        ticker = ticker.strip().upper()
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="5d")

        if hist.empty:
            return f"No data found for ticker: {ticker}"

        current = hist["Close"].iloc[-1]
        prev    = hist["Close"].iloc[-2] if len(hist) > 1 else current
        change  = current - prev
        pct     = (change / prev) * 100 if prev else 0

        name    = info.get("longName", ticker)
        mktcap  = info.get("marketCap", "N/A")
        pe      = info.get("trailingPE", "N/A")
        eps     = info.get("trailingEps", "N/A")
        week52h = info.get("fiftyTwoWeekHigh", "N/A")
        week52l = info.get("fiftyTwoWeekLow", "N/A")

        if isinstance(mktcap, (int, float)):
            if mktcap >= 1e12:
                mktcap_str = f"${mktcap/1e12:.2f}T"
            elif mktcap >= 1e9:
                mktcap_str = f"${mktcap/1e9:.2f}B"
            else:
                mktcap_str = f"${mktcap/1e6:.2f}M"
        else:
            mktcap_str = "N/A"

        arrow = "▲" if change >= 0 else "▼"
        return (
            f"📈 {name} ({ticker})\n"
            f"Price: ${current:.2f}  {arrow} {change:+.2f} ({pct:+.2f}%)\n"
            f"Market Cap: {mktcap_str}\n"
            f"P/E Ratio: {pe}\n"
            f"EPS: {eps}\n"
            f"52W High: {week52h}  |  52W Low: {week52l}"
        )
    except Exception as e:
        return f"Stock lookup failed for {ticker}: {str(e)}"


# ── Tool 4: Financial calculator ──────────────────────────────────────────────
@tool
def financial_calculator(expression: str) -> str:
    """
    Perform financial calculations. Supports:
    - Basic math: '1500 * 12 / 100'
    - ROI: 'roi: gain=5000, cost=20000'
    - CAGR: 'cagr: start=100, end=200, years=5'
    - Simple interest: 'si: principal=10000, rate=8, time=3'
    - Compound interest: 'ci: principal=10000, rate=8, time=3, n=12'
    - P/E ratio: 'pe: price=150, eps=10'
    """
    expr = expression.strip().lower()

    try:
        # ROI
        if expr.startswith("roi:"):
            parts = dict(re.findall(r"(\w+)=([\d.]+)", expr))
            gain = float(parts["gain"])
            cost = float(parts["cost"])
            roi  = (gain / cost) * 100
            return f"ROI = {roi:.2f}%"

        # CAGR
        if expr.startswith("cagr:"):
            parts = dict(re.findall(r"(\w+)=([\d.]+)", expr))
            start = float(parts["start"])
            end   = float(parts["end"])
            years = float(parts["years"])
            cagr  = ((end / start) ** (1 / years) - 1) * 100
            return f"CAGR = {cagr:.2f}% per year"

        # Simple interest
        if expr.startswith("si:"):
            parts = dict(re.findall(r"(\w+)=([\d.]+)", expr))
            p = float(parts["principal"])
            r = float(parts["rate"])
            t = float(parts["time"])
            si = (p * r * t) / 100
            return f"Simple Interest = {si:.2f}  |  Total = {p + si:.2f}"

        # Compound interest
        if expr.startswith("ci:"):
            parts = dict(re.findall(r"(\w+)=([\d.]+)", expr))
            p = float(parts["principal"])
            r = float(parts["rate"]) / 100
            t = float(parts["time"])
            n = float(parts.get("n", "1"))
            amount = p * (1 + r / n) ** (n * t)
            ci = amount - p
            return f"Compound Interest = {ci:.2f}  |  Total = {amount:.2f}"

        # P/E ratio
        if expr.startswith("pe:"):
            parts = dict(re.findall(r"(\w+)=([\d.]+)", expr))
            price = float(parts["price"])
            eps   = float(parts["eps"])
            pe    = price / eps
            return f"P/E Ratio = {pe:.2f}"

        # Generic math (safe eval)
        allowed = set("0123456789+-*/(). ")
        if all(c in allowed for c in expr):
            result = eval(expr)  # safe: only numbers + operators
            return f"Result = {result}"

        return "Invalid expression. Use formats like: roi: gain=X, cost=Y  or  1000 * 12"

    except Exception as e:
        return f"Calculation error: {str(e)}"


# Export all tools
ALL_TOOLS = [search_documents, web_search, get_stock_price, financial_calculator]
