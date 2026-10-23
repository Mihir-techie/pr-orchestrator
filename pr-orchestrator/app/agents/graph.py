from langgraph.graph import END, START, StateGraph

from app.agents.assignment_router import assignment_router
from app.agents.code_reviewer import code_reviewer
from app.agents.security_scanner import security_scanner
from app.agents.state import ReviewState

builder = StateGraph(ReviewState)
builder.add_node("code_reviewer", code_reviewer)
builder.add_node("security_scanner", security_scanner)
builder.add_node("assignment_router", assignment_router)
builder.add_edge(START, "code_reviewer")
builder.add_edge("code_reviewer", "security_scanner")
builder.add_edge("security_scanner", "assignment_router")
builder.add_edge("assignment_router", END)

review_graph = builder.compile()
