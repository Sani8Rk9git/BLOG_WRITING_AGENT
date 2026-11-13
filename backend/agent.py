# -------------------------
# 1. PACKAGES
# -------------------------

from pydantic import BaseModel, Field
from typing import Literal, List, Optional, TypedDict, Annotated

import operator # this is for the reducer function(define how the nodes will update the state)

import os
from dotenv import load_dotenv

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.types import Send
from langgraph.graph import StateGraph, START, END


import asyncio
from pathlib import Path
import sys


# --------------------------
# 2. SCHEMAS (define the output returned by the llm)
# --------------------------

# 2.1 Task pydantic model (define each section of the blog)
class Task(BaseModel):
    id_          : int = Field(..., description="Unique ID of the task")
    title        : str = Field(..., description="Title of the blog section or task")
    goal         : str = Field(..., description="One sentence describing what the reader should be able to do/understand after this section.")
    brief        : str = Field(..., description="Detailed instructions describing what the worker must accomplish")
    target_words : int = Field(..., ge=120, le=550, description="Target word count for this section (120-550).")
    worker_type  : Literal["introduction", "technical", "examples", "tutorial", "comparison", "conclusion"] = Field(..., description="The specialized worker responsible for completing this task.")


# 2.2 Plan pydantic model (define the plan for creating the blog, return by the orchestrator node)
class Plan(BaseModel):
    blog_title : str = Field(..., description="The final title of the blog")
    tasks      : List[Task] = Field(..., description="List of tasks assigned to specialized workers")

# 2.3 EvidenceItem pydantic model (define the things that must be stored when the internet search happen, return by research node)
class EvidenceItem(BaseModel):
    title        : str = Field(..., description="Title of the search")
    url          : str = Field(description="Url of the search")
    published_at : Optional[str] = None
    snippet      : Optional[str] = None # content of the search
    source       : Optional[str] = None

# 2.4 RouterDecision pydantic model (this is returned by router node based on the topic provided by the user)
class RouterDecision(BaseModel):
    needs_research : bool = Field(..., description="Whether there is a need to do the internet research.")
    mode           : Literal["closed_book", "hybrid", "open_book"] = Field(..., description="Whether there is no need to search on internet(closed_book), some part need to be search on the internet(hybrid), everything needs to be search on the internet(open_book)")
    queries        : List[str] = Field(default_factory=list, description="Search queries if research needed")


# 2.5 EvidencePack pydantic model (store the list of the result of the search)
class EvidencePack(BaseModel):
    evidence : List[EvidenceItem] = Field(..., description="Store the result of the query search")

# 2.6 BlogEvaluation pydantic model (evaluate the structure of the blog)
class BlogEvaluation(BaseModel):
    evaluation : Literal["approved", "need_improvement"] = Field(..., description="Evaluation of the blog.")
    feedback   : str = Field(...,description="Feedback for the orchestrator for the plan")



# ----------------------------
# 3. STATE OF THE WORKFLOW
# ----------------------------

class State(TypedDict):
    topic : str # topic of the blog given by user

    # given by router node
    mode : str
    needs_research : bool
    queries : List[str]

    # given by research node
    evidence : List[EvidenceItem]

    # given by the orchestrator node
    plan : Plan

    # given by worker nodes
    sections : Annotated[List[dict], operator.add] # add operator will combine the list of a string given by each worker node into a single List of strings

    # given by the reducer node
    final : str # this is the final blog 

    #given by the evaluator node
    evaluation    : Literal["approved", "need_improvement"]
    feedback      : str 
    iteration     : int # to track the number of iterations that are done
    max_iteration : int # to break the loop



# -------------------------
# 4. DEFINING THE LLMs
# -------------------------

# loading the environment variables
load_dotenv()

# 4.1 Planning llm
llm_plan = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("PLAN")
)

# 4.2 research llm
llm_research = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("RESEARCH")
)

# 4.3 introduction llm
llm_introduction = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("INTRODUCTION")
)

# 4.4 technical llm
llm_technical = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("TECHNICAL")
)

# 4.5 examples llm
llm_examples = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("EXAMPLES")
)

# 4.6 tutorial llm
llm_tutorial = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("TUTORIAL")
)

# 4.7 comparison llm
llm_comparison = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("COMPARISON")
)

# 4.8 conclusion llm
llm_conclusion = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("CONCLUSION")
)

# 4.9 router llm
llm_router = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("ROUTER")
)

# 4.10 evaluator llm
llm_evaluator = ChatGoogleGenerativeAI(
    model = "gemini-3.6-flash",
    api_key = os.getenv("EVALUATOR")
)



# --------------------------
# 5. Creating Parsers
# --------------------------

# 5.1 router parser
parser_router = PydanticOutputParser(pydantic_object = RouterDecision)

# 5.2 research parser
parser_research = PydanticOutputParser(pydantic_object = EvidencePack)

# 5.3 orchestrator parser
parser_orchestrator = PydanticOutputParser(pydantic_object = Plan)

# 5.4 evaluator parser
parser_evaluator = PydanticOutputParser(pydantic_object = BlogEvaluation)



# --------------------------
# MCP client for local FastMCP server
# ---------------------------

client = MultiServerMCPClient(
    {
        "search_web" : {
            "transport" : "stdio",
            "command" : sys.executable,
            "args" : [os.path.join(os.path.dirname(__file__),"mcp_server.py")]
        }
    }
)

# sys.executable gives the exact Python executable currently running your main program.


# ---------------------------
# Creating a llm registry
# ---------------------------

llm_registry = {
    "introduction" : llm_introduction, 
    "technical"    : llm_technical, 
    "examples"     : llm_examples, 
    "tutorial"     : llm_tutorial, 
    "comparison"   : llm_comparison, 
    "conclusion"   : llm_conclusion
}


# function for the graph

async def build_graph():

    # getting the tools from the mcp server
    tools = await client.get_tools()
    search_tool = next(tool for tool in tools if tool.name == "search_web")

    # -------------------------
    # 6. Defining the node functions
    # -------------------------
    
    # 6.1 router node function
    async def router_node(state: State) -> dict:
    
        topic = state["topic"]
        router_chain = llm_router | parser_router
    
        decision = await router_chain.ainvoke(
            [SystemMessage(content = f"""
            You are an intelligent research router for a multi-agent blog writing system.
            
            Your responsibility is to analyse the given blog topic and decide whether external internet research is required before the blog writing process begins.
    
            Follow these rules:
    
            1. CLOSED_BOOK:
               - Choose this when the topic involves stable concepts, fundamental knowledge, or general explanations.
               - No external research is necessary.
               - Set needs_research to False.
               - Return an empty queries list.
    
            2. HYBRID:
               - Choose this when the topic contains both stable concepts and information that may require external verification.
               - Research only the parts that require external information.
               - Set needs_research to True.
               - Generate relevant and specific search queries.
    
            3. OPEN_BOOK:
               - Choose this when the topic depends heavily on current, recent, or frequently changing information.
               - Examples include latest technologies, market trends, recent research papers, statistics, and current events.
               - Set needs_research to True.
               - Generate multiple focused search queries.
    
            {parser_router.get_format_instructions()}
            """),
            HumanMessage(content = f"""
            Analyse this blog topic and decide the research requirements:
    
            Blog topic : {topic}
            """)]
        )
    
        return {
            "needs_research" : decision.needs_research,
            "mode" : decision.mode,
            "queries" : decision.queries
        }
    
    # 6.2 function for the conditional edge 
    async def route_next(state: State) -> dict:
        return "research" if state["needs_research"] else "orchestrator"
    
    
    # 6.3 research node
    async def research_node(state: State) -> dict:
    
        # getting the queries from the state
        queries = (state.get("queries", []) or []) # Checks the state dictionary for the "queries" key. If the key does not exist, it defaults to an empty list [].
        # or []: Acts as a secondary fallback. If "queries" exists in state but its value is None (or another falsy value like an empty string ""), state.get() will return None. Evaluating None or [] forces the variable to become an empty list [].
    
        max_results = 6 # for each query, we will fetch 6 results
    
        raw_results: List[dict] = []
    
        for q in queries:
            result = await search_tool.ainvoke({"query":q, "max_results": max_results})

            raw_results.extend(result)
    
        if not raw_results:
            return {"evidence" : []}
    
        research_chain = llm_research | parser_research
    
        pack = await research_chain.ainvoke(
            [SystemMessage(content=f"""
            You are a Research Analyst in a multi-agent blog writing system.

            Your task is to analyze web search results and convert useful information into structured evidence for blog-writing agents.

            Follow these rules:

            1. Filter out irrelevant, duplicate, and low-quality results.
            2. Extract important facts, statistics, examples, and insights.
            3. Prefer reliable sources such as official documentation, research papers, and reputable publications.
            4. Preserve original source titles and URLs.
            5. Never invent facts, dates, statistics, or sources.
            6. Use only the supplied search results. Do not assume snippets represent the complete webpage.
            7. Keep evidence relevant, concise, and informative.
            8. If no useful information is available, return an empty list.

            Do not write the blog, create an outline, or generate queries.

            Return ONLY the output in the EvidencePack format.

            {parser_research.get_format_instructions()}

            """),
            HumanMessage(content=f"""
            Blog Topic : {state["topic"]}.

            Research Mode : {state["mode"]}.

            Search queries: {queries}.

            Raw Search Results: 
            {raw_results}
            """)]
        )

        return {"evidence" : pack.evidence}


    # 6.4 orchestrator node
    async def orchestrator(state: State) -> dict:

        plan_chain = llm_plan | parser_orchestrator

        evidence = state.get("evidence", [])
        mode = state.get("mode", "closed_book")

        plan = await plan_chain.ainvoke(
            [SystemMessage(content=f"""
            You are an expert Blog Planning Orchestrator in a multi-agent blog writing system.

            Your task is to analyze the given blog topic and create a structured plan by dividing it into logical sections.

            Follow these rules:

            1. Understand the topic, its purpose, and target audience.
            2. Create a suitable and engaging blog title.
            3. Divide the blog into logically ordered sections.
            4. Assign each section a clear goal and brief description.
            5. Set an appropriate target word count for each section.
            6. Assign the most suitable worker_type to each task.
            7. Ensure sections flow naturally and avoid repetition.
            8. Include all important aspects of the topic.

            Create a complete plan that specialized writing agents can independently execute.
            
            Return ONLY the structured output in the Plan format.

            {parser_orchestrator.get_format_instructions()}
            """),
            HumanMessage(content=f"""
            Topic : {state["topic"]}.
            Mode  : {mode}.
            Evidence (ONLY use for fresh claims; may be empty): {[e.model_dump() for e in evidence]}.
            Feedback (Revise the plan based on the feedback also; may be empty) : {state.get("feedback", "")}
            """)]
        )

        return {"plan" : plan}

    # defining a function 
    #    - check how many tasks are present in the plan object(the number of sections planned by the orchestrator node.)
    #    - for each section, it will trigger a worker node and send a payload also(a dictionary that contains information about that task)
    # LangGraph's Send API allows you to dynamically create multiple executions of the same node.

    async def fanout(state: State):
        return [Send("worker", {"task":task, "topic":state["topic"], "plan":state["plan"], "evidence" : [e.model_dump() for e in state.get("evidence", [])], "iteration" : state["iteration"], "feedback":state.get("feedback","")}) for task in state["plan"].tasks]


    # worker node
    async def worker(payload: dict) -> dict:

        # payload contains what we send by the fanout function
        task = payload["task"]
        topic = payload["topic"]
        plan = payload["plan"]
        evidence = payload["evidence"]
        feedback = payload["feedback"]
        iteration = payload["iteration"]

        blog_title = plan.blog_title
        
        # select LLM based on task type
        llm = llm_registry[task.worker_type]

    
        prompt = [
            SystemMessage(content=f"""
            You are a professional blog writer.

            Blog title: {blog_title} and 
            Main topic: {topic} and
            
            Your assigned section: 
            {task.title} and
            
            Instructions:
            {task.brief}.

            Evidence:
            {evidence}

            Goal:
            {task.goal}

            Target Words:
            {task.target_words}

            Previous evaluation feedback(may be empty):
            {feedback}

            Follow the feedback when improving the section.
            
            Write a detailed, informative section.
            Do not write the introduction or conclusion unless specifically assigned.
            """),
            HumanMessage(content="Write your assigned section.")
        ]
    
        response = await llm.ainvoke(prompt)

        section = response.text.strip()
    
        return {"sections" : [{"id" : task.id_, "content" : section, "iteration": iteration}]}

    # reducer node
    async def reducer(state: State) -> dict:
        title = state["plan"].blog_title
        sections = [section for section in state["sections"] if section["iteration"] == state["iteration"]]
        sections = sorted(sections, key=lambda x: x["id"]) # sort according to the id 
        body = "\n\n".join(section["content"] for section in sections).strip() # joining the sections with the line change.
    
        final = f"# {title}\n\n{body}\n" # this is the complete blog
    
        # save the blog in the file
        # filename = "blog_output.md"
        filename = "".join(c if c.isalnum() or c in (" ", "_", "-") else "" for c in title)
        filename = filename.strip().lower().replace(" ", "_") + ".md"
    
        output_path = Path(filename)
        output_path.write_text(final, encoding="utf-8")
    
        return {"final" : final}

    # evaluation node
    async def evaluate(state: State) -> dict:

        evaluate_chain = llm_evaluator | parser_evaluator

        response = await evaluate_chain.ainvoke(
            [SystemMessage(content=f"""
            You are an expert Blog Quality Evaluator in a multi-agent blog writing system.

            Your task is to evaluate the final blog against the original plan and determine whether it is ready for publication.

            Evaluate the blog based on:

            1. RELEVANCE: Does it properly address the given topic?
            2. COMPLETENESS: Are all planned sections included?
            3. ACCURACY: Is the information clear and factually reliable?
            4. STRUCTURE: Do sections follow a logical order and flow?
            5. QUALITY: Is the content informative, readable, and free from unnecessary repetition?
            6. INSTRUCTIONS: Does each section satisfy its assigned goal?

            Decision:
            - approved: If the blog meets the required quality standards.
            - need_improvement: If important issues need to be corrected.
            
            If improvement is needed, provide specific and actionable
            feedback explaining what should be fixed.
            
            Do not rewrite the blog yourself.
            
            Return ONLY the structured BlogEvaluation output.

            {parser_evaluator.get_format_instructions()}
            """),
            HumanMessage(content=f""".
            plan : {state["plan"]},
            Final blog : {state["final"]}
            """)]
        )

        iteration = state["iteration"] + 1

        return {"evaluation" : response.evaluation, "feedback" : response.feedback, "iteration" : iteration}


    # creating the conditional edge function 
    async def check_evaluation(state: State):
        if state["evaluation"] == "approved" or state["iteration"] >= state["max_iteration"]:
            return "approved"
        else:
            return "need_improvement"


    # -----------------------------
    # Defining the Graph
    # ----------------------------

    g = StateGraph(State)

    # adding nodes
    g.add_node("router", router_node)
    g.add_node("research", research_node)
    g.add_node("orchestrator", orchestrator)
    g.add_node("worker", worker)
    g.add_node("reducer", reducer)
    g.add_node("evaluate", evaluate)

    # adding edges
    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_next, {"research" : "research", "orchestrator": "orchestrator"})
    g.add_edge("research", "orchestrator")

    g.add_conditional_edges("orchestrator", fanout, ["worker"])
    g.add_edge("worker", "reducer")
    g.add_edge("reducer", "evaluate")

    g.add_conditional_edges("evaluate", check_evaluation, {"approved" : END, "need_improvement" : "orchestrator"})

    blog_agent = g.compile()

    return blog_agent


async def main():
    blog_agent = await build_graph()

    output = await blog_agent.ainvoke({"topic": "Write a detailed blog on the evolution of AI agents in 2026. Cover the latest agentic AI frameworks, multi-agent architectures, real-world business applications, recent developments, and future trends.", "iteration" : 1, "max_iteration" : 5})
    # ainvoke is asynchronous invoke
    print(output)

if __name__ == "__main__":
    asyncio.run(main())