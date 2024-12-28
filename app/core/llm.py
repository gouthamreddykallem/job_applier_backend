# llm.py

from dotenv import load_dotenv
from langchain.prompts import PromptTemplate
from langchain_huggingface import HuggingFaceEndpoint
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.chains import LLMChain
from typing import List, Dict
import logging
import os
import json

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AINavigator:
    def __init__(self):
        self.hf_token = os.getenv("HUGGINGFACEHUB_API_TOKEN")
        self.repo_id = os.getenv("REPO_ID", "mistralai/Mistral-7B-Instruct-v0.2")
        
        if not self.hf_token:
            raise ValueError("HUGGINGFACEHUB_API_TOKEN environment variable not set")
            
        self.llm = None
        self.embeddings = None
        
    async def init_model(self):
        """Initialize the model and embeddings"""
        try:
            logger.info("Initializing HuggingFace endpoint and embeddings")
            
            # Initialize LLM with proper configuration
            self.llm = HuggingFaceEndpoint(
                repo_id=self.repo_id,
                task="text-generation",
                max_new_tokens=512,
                temperature=0.7,
                top_p=0.95,
                top_k=50,
                repetition_penalty=1.03,
                huggingfacehub_api_token=self.hf_token
            )
            
            # Initialize embeddings model
            embeddings_model = os.getenv("EMBEDDINGS_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
            self.embeddings = HuggingFaceEmbeddings(
                model_name=embeddings_model,
                model_kwargs={'device': os.getenv("DEVICE", "cpu")}
            )
            
            logger.info(f"AI Navigator initialized successfully with model {self.repo_id}")
            
        except Exception as e:
            logger.error(f"Error initializing AI Navigator: {str(e)}")
            raise

    async def verify_state(self, page_content: Dict, target_state: str) -> Dict:
        """Verify if current page matches target state"""
        try:
            # Simplified template with properly formatted input variables
            template = """
            Task: Verify if the current webpage matches the target state.

            Current Page Information:
            URL: {current_url}
            Title: {page_title}
            Content: {page_content}
            Target State: {desired_state}

            Based on the above information, determine if the current page matches the target state.
            Return your analysis in valid JSON format with the following structure:
            {{
                "success": boolean,
                "confidence": float between 0 and 1,
                "missing_requirements": array of strings
            }}
            """
            
            prompt = PromptTemplate(
                template=template,
                input_variables=["current_url", "page_title", "page_content", "desired_state"]
            )
            
            chain = LLMChain(llm=self.llm, prompt=prompt)
            
            # Execute the chain with properly mapped variables
            response = await chain.arun(
                current_url=page_content.get('url', ''),
                page_title=page_content.get('title', ''),
                page_content=page_content.get('text', '')[:1000],
                desired_state=target_state
            )
            
            try:
                verification = json.loads(response.strip())
                return verification
            except json.JSONDecodeError:
                logger.error("Failed to parse verification response")
                return {"success": False, "confidence": 0, "missing_requirements": ["parsing_error"]}
            
        except Exception as e:
            logger.error(f"Error during state verification: {str(e)}")
            return {"success": False, "confidence": 0, "missing_requirements": [str(e)]}

    async def get_navigation_plan(self, page_content: Dict, target_state: str) -> Dict:
        try:
            template = """
            Task: Create a navigation plan to reach the target state.
            Current Page Information:
            URL: {current_url}
            Title: {page_title}
            Elements: {page_elements}
            Target State: {desired_state}
            Create a detailed plan to navigate from the current state to the target state.
            Return your plan in valid JSON format with the following structure:
            {{
            "status": string,
            "actions": [
                {{
                "type": string (click/fill/navigate/select),
                "selector": string,
                "value": string (optional),
                "description": string
                }}
            ]
            }}
            """
            prompt = PromptTemplate(
                template=template,
                input_variables=["current_url", "page_title", "page_elements", "desired_state"]
            )
            chain = LLMChain(llm=self.llm, prompt=prompt)
            response = await chain.arun(
                current_url=page_content.get('url', ''),
                page_title=page_content.get('title', ''),
                page_elements=json.dumps(page_content.get('elements', [])),
                desired_state=target_state
            )
            try:
                plan = json.loads(response.strip())
                return plan
            except json.JSONDecodeError:
                logger.error("Failed to parse navigation plan")
                return {"status": "error", "message": "Invalid plan format", "actions": []}
        except Exception as e:
            logger.error(f"Error generating navigation plan: {str(e)}")
            return {"status": "error", "message": str(e), "actions": []}




    async def verify_state(self, page_content: Dict, target_state: str) -> Dict:
        try:
            template = """
            Task: Verify if the current webpage matches the target state.
            Current Page Content:
            URL: {url}
            Title: {title}
            Text Content: {text}
            Target State: {target_state}
            Required:
            1. Analyze if current page matches target state
            2. Identify any missing requirements
            3. Provide confidence score
            Return JSON:
            {{
            "success": true/false,
            "confidence": 0-1,
            "missing_requirements": [list if any]
            }}
            Response:
            """
            prompt = PromptTemplate(
                input_variables=["url", "title", "text", "target_state"],
                template=template
            )
            chain = LLMChain(llm=self.llm, prompt=prompt)
            response = await chain.arun(
                url=page_content['url'],
                title=page_content['title'],
                text=page_content['text'][:1000],  # Limit text length
                target_state=target_state
            )
            try:
                verification = json.loads(response.strip())
                return verification
            except json.JSONDecodeError:
                logger.error("Failed to parse verification response as JSON")
                return {"success": False, "confidence": 0, "missing_requirements": ["parsing_error"]}
        except Exception as e:
            logger.error(f"Error during state verification: {str(e)}")
            return {"success": False, "confidence": 0, "missing_requirements": [str(e)]}



    async def analyze_search_results(self, page_content: Dict, company_name: str) -> Dict:
        """Analyze search results for valid career portals"""
        try:
            template = """
            Task: Analyze search results to identify valid career portals for the company.

            Company Name: {company_name}
            Search Results: {search_results}

            Required:
            1. Identify official company career portals
            2. Filter out third-party job boards
            3. Rank results by relevance
            4. Provide confidence scores

            Return JSON:
            {
                "status": "success",
                "results": [
                    {
                        "url": "url",
                        "title": "title",
                        "confidence": 0-1,
                        "is_official": true/false
                    }
                ]
            }

            Response:
            """
            
            prompt = PromptTemplate(
                input_variables=["company_name", "search_results"],
                template=template
            )
            
            chain = LLMChain(llm=self.llm, prompt=prompt)
            
            response = await chain.arun(
                company_name=company_name,
                search_results=json.dumps(page_content['elements'])
            )
            
            try:
                analysis = json.loads(response.strip())
                return analysis
            except json.JSONDecodeError:
                logger.error("Failed to parse search results analysis")
                return {"status": "error", "message": "Invalid analysis format"}
            
        except Exception as e:
            logger.error(f"Error analyzing search results: {str(e)}")
            return {"status": "error", "message": str(e)}