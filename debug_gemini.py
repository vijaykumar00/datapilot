"""Debug: print exactly what Gemini returns for the SQL prompt"""
import asyncio, os, sys
sys.path.insert(0, "backend")
os.chdir("backend")

from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai

api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.0-flash")

SQL_SYSTEM = """You are a SQL expert. Generate a single DuckDB SQL SELECT query for the user's question.

Rules:
1. Return ONLY valid JSON: {"sql": "<sql_query>", "explanation": "<one sentence>"}
2. Use the table name provided exactly as given
3. Use LIMIT 100 for safety unless user asks for all rows
4. For aggregations, use GROUP BY and ORDER BY DESC
5. Never use DELETE, DROP, INSERT, UPDATE — only SELECT

Few-shot examples:
Q: top 5 products by revenue | table: file_abc123
A: {"sql": "SELECT product, SUM(revenue) as total_revenue FROM file_abc123 GROUP BY product ORDER BY total_revenue DESC LIMIT 5", "explanation": "Groups by product and sums revenue"}
"""

prompt = """Table: file_test
Columns: "month" (object), "product" (object), "sales" (int64), "revenue" (int64), "region" (object)
Sample values: [{'month': '2024-01', 'product': 'Widget A', 'sales': 150, 'revenue': 7500, 'region': 'North'}]
Question: which product has the highest total revenue?"""

full = f"{SQL_SYSTEM}\n\n{prompt}"
response = model.generate_content(full)
print("=== RAW GEMINI OUTPUT ===")
print(repr(response.text))
print("\n=== DISPLAYED ===")
print(response.text)
