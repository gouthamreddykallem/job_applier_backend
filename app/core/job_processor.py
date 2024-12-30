# job_processor.py

from typing import List, Dict, Optional
import asyncio
import logging
from datetime import datetime
from playwright.async_api import Page, Browser
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class JobPosition:
    title: str
    url: str
    company: str
    location: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None
    match_score: float = 0.0

class JobApplicationProcessor:
    def __init__(self, browser_automation, ai_navigator):
        self.browser = browser_automation
        self.ai = ai_navigator
        self.active_applications = {}
        self.completed_applications = {}
        self.failed_applications = {}

    async def process_job_applications(self, application_data: Dict) -> Dict:
        """
        Main workflow handler for processing multiple job applications
        """
        try:
            # Initialize tracking
            process_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.active_applications[process_id] = {
                "status": "initiated",
                "jobs_found": 0,
                "applications_submitted": 0,
                "applications_failed": 0,
                "start_time": datetime.now().isoformat()
            }

            # Step 1: Find career portal and job listings
            career_portal = await self._find_career_portal(application_data["company_name"])
            if not career_portal:
                raise Exception(f"Could not find career portal for {application_data['company_name']}")

            # Step 2: Search and collect relevant jobs
            relevant_jobs = await self._search_relevant_jobs(
                career_portal,
                application_data["position_title"],
                application_data.get("location")
            )
            logger.debug(relevant_jobs)

            self.active_applications[process_id]["jobs_found"] = len(relevant_jobs)

            # Step 3: Process each relevant job in parallel
            tasks = []
            for job in relevant_jobs:
                task = asyncio.create_task(
                    self._process_single_application(job, application_data, process_id)
                )
                tasks.append(task)

            # Wait for all applications to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Update final statistics
            success_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "success")
            self.active_applications[process_id].update({
                "status": "completed",
                "applications_submitted": success_count,
                "applications_failed": len(results) - success_count,
                "end_time": datetime.now().isoformat()
            })

            return {
                "status": "success",
                "process_id": process_id,
                "summary": self.active_applications[process_id]
            }

        except Exception as e:
            logger.error(f"Error in batch processing: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def _find_career_portal(self, company_name: str) -> Optional[str]:
        """
        Find and verify company career portal using AI analysis.
        
        Args:
            company_name: Name of the company to search for
            
        Returns:
            Optional[str]: URL of the best matching career portal, or None if not found
        """
        try:
            # Search for potential career portals
            search_results = await self.browser.search_career_portal(company_name)
            if search_results["status"] == "error":
                logger.error(f"Error searching for career portal: {search_results.get('message')}")
                return None

            # Use AI to analyze the results
            analysis = await self.ai.analyze_career_portal_results(
                search_results["results"],
                company_name
            )

            if analysis["status"] == "error":
                logger.error(f"Error analyzing career portals: {analysis.get('message')}")
                return None

            best_match = analysis.get("best_match", {})
            if best_match and best_match.get("confidence", 0) > 0.7:
                logger.info(f"Found career portal for {company_name}: {best_match['url']}")
                logger.info(f"Selection reasoning: {best_match.get('reasoning', [])}")
                
                # Verify the portal is accessible
                try:
                    await self.browser.page.goto(best_match['url'])
                    await self.browser.wait_for_page_load()
                    
                    logger.info("Navigated to career portal")
                    
                    # Additional verification of page content
                    page_content = await self.browser.get_page_content()
                    verification = await self.ai.verify_state(
                        page_content,
                        "career or job portal"
                    )
                    # logger.info("Career portal status verified",str(verification.get("success", False)) )
                    
                    if verification.get("success", False):
                        return best_match['url']
                    else:
                        logger.warning("Selected portal failed content verification")
                        
                        # Try alternatives if available
                        for alt in analysis.get("alternatives", []):
                            if alt.get("confidence", 0) > 0.6:
                                await self.browser.page.goto(alt['url'])
                                await self.browser.wait_for_page_load()
                                
                                alt_verification = await self.ai.verify_state(
                                    await self.browser.get_page_content(),
                                    "career or job portal"
                                )
                                
                                if alt_verification.get("success", False):
                                    return alt['url']
                
                except Exception as e:
                    logger.error(f"Error verifying career portal: {str(e)}")
                    # If primary URL fails, try alternatives
                    for alt in analysis.get("alternatives", []):
                        if alt.get("confidence", 0) > 0.6:
                            try:
                                await self.browser.page.goto(alt['url'])
                                await self.browser.wait_for_page_load()
                                return alt['url']
                            except:
                                continue

            logger.warning(f"No suitable career portal found for {company_name}")
            return None

        except Exception as e:
            logger.error(f"Error in career portal search process: {str(e)}")
            return None

    async def _search_relevant_jobs(
        self,
        career_portal: str,
        position_title: str,
        location: Optional[str] = None
    ) -> List[JobPosition]:
        """Search and collect relevant job positions"""
        # Navigate to career portal
        
        await self.browser.page.goto(career_portal)
        await self.browser.wait_for_page_load()
        logger.info("Started searching for jobs")

        # Find and interact with search functionality
        search_result = await self.browser.navigate_with_ai("job search page")
        if search_result["status"] == "error":
            return []

        # Perform search
        if location:
            search_query = f"{position_title} {location}"
        else:
            search_query = position_title
        logger.info(f"search_query is: {search_query}")

        # Find search input and submit
        try:
            search_input = await self.browser.page.wait_for_selector('input[type="search"], input[type="text"]')
            await search_input.fill(search_query)
            await search_input.press('Enter')
            await self.browser.wait_for_page_load()
        except Exception as e:
            logger.error(f"Error performing job search: {str(e)}")
            return []

        # Extract job listings
        listings_result = await self.browser.analyze_job_listings()
        logger.info(f"listings_result: {listings_result}")
        if listings_result["status"] == "error":
            return []

        # Convert to JobPosition objects and filter relevant ones
        relevant_jobs = []
        for listing in listings_result["listings"]:
            # Calculate match score
            match_score = await self._calculate_job_match(listing, position_title)
            
            if match_score > 0.7:  # Threshold for relevance
                job = JobPosition(
                    title=listing["title"],
                    url=listing["link"],
                    company=listing.get("company", ""),
                    location=listing.get("location", ""),
                    description=listing.get("description", ""),
                    department=listing.get("department", ""),
                    match_score=match_score
                )
                relevant_jobs.append(job)

        return relevant_jobs

    async def _calculate_job_match(self, listing: Dict, target_position: str) -> float:
        """Calculate match score between job listing and target position"""
        try:
            # Use the new analyze_job_relevance method
            match_score = await self.ai.analyze_job_relevance(listing, target_position)
            
            # Apply additional scoring factors
            score = match_score
            
            # Boost score if title matches closely
            if target_position.lower() in listing["title"].lower():
                score = min(score + 0.2, 1.0)
                
            # Penalize if location doesn't match (if specified)
            if listing.get("location") and "remote" not in listing["location"].lower():
                score *= 0.9
                
            return score
            
        except Exception as e:
            logger.error(f"Error calculating job match: {str(e)}")
            return 0.0

    async def _process_single_application(
        self,
        job: JobPosition,
        application_data: Dict,
        process_id: str
    ) -> Dict:
        """Process application for a single job position"""
        try:
            # Create new page for this application
            new_page = await self.browser.browser.new_page()
            
            # Navigate to job posting
            await new_page.goto(job.url)
            await self._wait_for_page_load(new_page)

            # Find apply button and click
            apply_button = await new_page.wait_for_selector(
                'button:has-text("Apply"), a:has-text("Apply")'
            )
            await apply_button.click()
            await self._wait_for_page_load(new_page)

            # Fill application form
            form_result = await self._fill_application_form(
                new_page,
                application_data
            )

            if form_result["status"] == "success":
                # Submit application
                submit_result = await self._submit_application(new_page)
                
                if submit_result["status"] == "success":
                    self.completed_applications[job.url] = {
                        "job": job,
                        "submission_time": datetime.now().isoformat(),
                        "status": "submitted"
                    }
                    return {"status": "success", "job": job.title}
                
            # If we get here, application failed
            self.failed_applications[job.url] = {
                "job": job,
                "error": form_result.get("message", "Unknown error"),
                "time": datetime.now().isoformat()
            }
            return {"status": "error", "job": job.title, "error": form_result.get("message")}

        except Exception as e:
            logger.error(f"Error processing application for {job.title}: {str(e)}")
            return {"status": "error", "job": job.title, "error": str(e)}
        finally:
            await new_page.close()

    async def _wait_for_page_load(self, page: Page):
        """Wait for page to be fully loaded"""
        try:
            await page.wait_for_load_state('networkidle')
            await page.wait_for_load_state('domcontentloaded')
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Timeout waiting for page load: {str(e)}")

    async def _fill_application_form(self, page: Page, application_data: Dict) -> Dict:
        """Fill out the job application form"""
        try:
            # Get form structure
            form_content = await self._get_page_content(page)
            
            # Get AI-generated form fill plan
            form_plan = await self.ai.get_form_fill_plan(form_content, application_data)
            
            if form_plan["status"] == "error":
                return form_plan

            # Execute each form fill action
            for action in form_plan["actions"]:
                success = await self._execute_form_action(page, action)
                if not success:
                    return {
                        "status": "error",
                        "message": f"Failed to execute form action: {action}"
                    }

            return {"status": "success"}

        except Exception as e:
            logger.error(f"Error filling application form: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def _submit_application(self, page: Page) -> Dict:
        """Submit the completed application form"""
        try:
            submit_button = await page.wait_for_selector(
                'button[type="submit"], input[type="submit"]'
            )
            await submit_button.click()
            await self._wait_for_page_load(page)

            # Verify submission success
            success_indicators = [
                "thank you",
                "application received",
                "successfully submitted",
                "application complete"
            ]

            page_content = await page.text_content("body")
            if any(indicator in page_content.lower() for indicator in success_indicators):
                return {"status": "success"}
            
            return {
                "status": "error",
                "message": "Could not verify submission success"
            }

        except Exception as e:
            logger.error(f"Error submitting application: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def _get_page_content(self, page: Page) -> Dict:
        """Extract content from the given page"""
        try:
            return {
                'url': page.url,
                'title': await page.title(),
                'text': await page.evaluate('() => document.body.innerText'),
                'html': await page.content(),
                'elements': await page.evaluate('''
                    () => Array.from(document.querySelectorAll('input, button, select, textarea'))
                        .map(el => ({
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            id: el.id || null,
                            name: el.name || null,
                            placeholder: el.placeholder || null
                        }))
                ''')
            }
        except Exception as e:
            logger.error(f"Error extracting page content: {str(e)}")
            return {}

    async def _execute_form_action(self, page: Page, action: Dict) -> bool:
        """Execute a single form fill action"""
        try:
            action_type = action.get('type')
            selector = action.get('selector')
            value = action.get('value')

            if not selector or not action_type:
                return False

            element = await page.wait_for_selector(selector)
            if not element:
                return False

            if action_type == 'fill':
                await element.fill(value)
            elif action_type == 'select':
                await element.select_option(value)
            elif action_type == 'click':
                await element.click()
            elif action_type == 'upload':
                await element.set_input_files(value)
            else:
                return False

            await asyncio.sleep(0.5)  # Small delay after each action
            return True

        except Exception as e:
            logger.error(f"Error executing form action: {str(e)}")
            return False