from crewai import Crew
from langchain_anthropic import ChatAnthropic
from ai_research_tasks import *
from ai_research_agents import *

class AIResearchCrew:
    def __init__(self, email_subject, email_body, email_from):
        self.email_subject = email_subject
        self.email_body = email_body
        self.email_from = email_from

    def run(self):
        crew = Crew(
            agents=[administrative_assistant,
                    researcher,
                    writer],
            tasks=[parse_research_request,
                   conduct_research,
                   rewrite_report_to_email],
            verbose=2,
            manager_llm=ChatAnthropic(
                temperature=0.5,
                model="claude-3-5-sonnet-20240620"
            ),
            planning=True,
            planning_llm=ChatAnthropic(
                temperature=0.5,
                model="claude-3-5-sonnet-20240620"
            ),
            max_iter=15,
        )

        results = crew.kickoff({"email_subject": self.email_subject, "email_body": self.email_body, "email_from": self.email_from})
        return results
