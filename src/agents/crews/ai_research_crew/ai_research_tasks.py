from crewai import Task
from ai_research_agents import administrative_assistant, researcher, writer
from pydantic import BaseModel


class ResearchReport(BaseModel):
  research_report: str
  email_from: str
  email_subject: str
  email_body: str


# Create tasks for your agents
parse_research_request = Task(
  description="""Parse the email subject {email_subject} and body {email_body} to determine the topic or topics for the research""",
  expected_output="""Clearly state the topic or topics that the email is referring to as {list_of_topics}""",
  agent=administrative_assistant,
)

conduct_research = Task(
  description="""
    You will receive a topic or list of topics as {list_of_topics} to research. You will research each topic and provide a detailed report of the information you find.
  """,
  expected_output='A comprehensive report on the topic or topics researched as {research_report}',
  agent=researcher,
  context=[parse_research_request]
)

rewrite_the_report = Task(
  description="""Using the research reports from the researcher's report,
  develop a nicely formated research report. Your final answer MUST be a full report and should also contain
  a set of bullet points with the key facts at the beginning for a summary. 
  It should use very simple language and be easy to read. 
  It should be a full report and not just a summary, with statistics where necessary.
  It should contain all sources used for the information from research.
  <RESEARCH_REPORT>
  {research_report}
  </RESEARCH_REPORT>
  """,
  expected_output="""A well-formated research report in an easy readable manner.""",
  agent=writer,
  context=[conduct_research]
)

rewrite_report_to_email = Task(
  description="""Take the research report and rewrite it to be an email response to the original email request from {email_from}, with the subject {email_subject} and body {email_body}""",
  expected_output="""A well-formated email response to the original email request.""",
  agent=administrative_assistant,
  context=[rewrite_the_report, parse_research_request],
  output_json=ResearchReport,
)