# browser.py

from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
from typing import Optional, Dict, List
import asyncio
import logging
from datetime import datetime
from app.core.llm import AINavigator  # Add this import

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BrowserAutomation:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.ai_navigator: Optional[AINavigator] = None
        self.timeout = 30000  # 30 seconds timeout
        
    async def init_browser(self):
        """Initialize browser instance and AI navigator"""
        try:
            # Initialize Playwright
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(headless=False)
            self.page = await self.browser.new_page()
            await self.page.set_viewport_size({"width": 1280, "height": 720})
            
            # Set default navigation timeout
            self.page.set_default_navigation_timeout(self.timeout)
            self.page.set_default_timeout(self.timeout)
            
            # Initialize AI Navigator
            self.ai_navigator = AINavigator()
            await self.ai_navigator.init_model()
            
            logger.info("Browser and AI Navigator initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize browser or AI Navigator: {str(e)}")
            raise

    async def ensure_ai_navigator(self):
        """Ensure AI Navigator is initialized"""
        if not self.ai_navigator:
            self.ai_navigator = AINavigator()
            await self.ai_navigator.init_model()

    async def wait_for_page_load(self):
        """Wait for page to be fully loaded"""
        try:
            # Wait for network to be idle
            await self.page.wait_for_load_state('networkidle')
            
            # Wait for document to be loaded
            await self.page.wait_for_load_state('domcontentloaded')
            
            # Additional wait for dynamic content
            await self.page.wait_for_function("""
                () => {
                    return document.readyState === 'complete' && 
                           document.body !== null && 
                           document.body.children.length > 0;
                }
            """)
            
            # Small additional delay for any final dynamic content
            await asyncio.sleep(2)
            
        except PlaywrightTimeout:
            logger.warning("Page load timeout - continuing with partial load")
        except Exception as e:
            logger.error(f"Error waiting for page load: {str(e)}")
            raise

    # browser.py

    async def navigate_with_ai(self, target_state: str) -> Dict:
        """
        AI-guided navigation to reach a target state
        """
        logger.info(f"navigate_with_ai start for: {target_state} ")
        try:
            if not hasattr(self, 'ai_navigator') or self.ai_navigator is None:
                from app.core.llm import AINavigator
                self.ai_navigator = AINavigator()
                await self.ai_navigator.init_model()
            
            max_attempts = 5
            current_attempt = 0
            
            while current_attempt < max_attempts:
                # Get current page content
                page_content = await self.get_page_content()
                # logger.info("Attempt no:  ", str(current_attempt))
                
                # Verify if we've reached the target state
                state_verification = await self.ai_navigator.verify_state(page_content, target_state)
                logger.info(f"state_verification: {state_verification.get('success', False)}")
                if state_verification.get('success', False):
                    return {
                        "status": "success",
                        "message": f"Reached target state: {target_state}",
                        "confidence": state_verification.get('confidence', 0)
                    }
                
                # Get navigation plan from AI
                nav_plan = await self.ai_navigator.get_navigation_plan(page_content, target_state)
                
                if nav_plan["status"] == "error":
                    return nav_plan
                
                # Execute each action in the plan
                for action in nav_plan.get("actions", []):
                    success = await self.execute_action(action)
                    if not success:
                        logger.warning(f"Action failed: {action}")
                        continue
                    
                    # Wait for page to settle after action
                    await self.wait_for_page_load()
                    
                    # Check if action led to target state
                    current_state = await self.ai_navigator.verify_state(
                        await self.get_page_content(), 
                        target_state
                    )
                    if current_state.get('success', False):
                        return {
                            "status": "success",
                            "message": f"Reached target state: {target_state}",
                            "confidence": current_state.get('confidence', 0)
                        }
                
                current_attempt += 1
                
            return {
                "status": "error",
                "message": f"Failed to reach target state after {max_attempts} attempts"
            }
            
        except Exception as e:
            logger.error(f"Error during AI-guided navigation: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def analyze_job_listings(self) -> Dict:
        """
        Analyze job listings on the current page
        """
        logger.info("Start of analyze_job_listings")
        try:
            page_content = await self.get_page_content()
            
            # Extract job listings using page evaluation
            listings = await self.page.evaluate('''
                () => {
                    const listings = [];
                    // Common job listing selectors
                    const jobCards = document.querySelectorAll('div[class*="job"], div[class*="position"], div[class*="career"]');
                    
                    jobCards.forEach(card => {
                        const listing = {
                            title: '',
                            location: '',
                            department: '',
                            link: '',
                            description: ''
                        };
                        
                        // Extract text content
                        listing.title = card.querySelector('h2, h3, h4, [class*="title"]')?.innerText || '';
                        listing.location = card.querySelector('[class*="location"]')?.innerText || '';
                        listing.department = card.querySelector('[class*="department"]')?.innerText || '';
                        
                        // Extract link
                        const linkEl = card.querySelector('a');
                        if (linkEl) {
                            listing.link = linkEl.href;
                        }
                        
                        // Extract description
                        const descEl = card.querySelector('[class*="description"], [class*="summary"]');
                        if (descEl) {
                            listing.description = descEl.innerText;
                        }
                        
                        if (listing.title) {
                            listings.push(listing);
                        }
                    });
                    
                    return listings;
                }
            ''')
            
            return {
                "status": "success",
                "listings": listings
            }
            
        except Exception as e:
            logger.error(f"Error analyzing job listings: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def submit_application_form(self, application_data: Dict) -> Dict:
        """
        Fill and submit job application form
        """
        try:
            # Verify we're on an application form
            page_content = await self.get_page_content()
            form_verification = await self.ai_navigator.verify_state(page_content, "application_form")
            
            if not form_verification.get('success', False):
                return {
                    "status": "error",
                    "message": "Not on application form page"
                }
            
            # Get form fill plan from AI
            form_plan = await self.ai_navigator.get_form_fill_plan(page_content, application_data)
            
            if form_plan["status"] == "error":
                return form_plan
            
            # Execute form filling actions
            for action in form_plan.get("actions", []):
                success = await self.execute_action(action)
                if not success:
                    return {
                        "status": "error",
                        "message": f"Failed to execute form action: {action}"
                    }
            
            # Final verification before submission
            await self.wait_for_page_load()
            final_check = await self.ai_navigator.verify_form_completion(
                await self.get_page_content(),
                application_data
            )
            
            if not final_check.get('success', False):
                return {
                    "status": "error",
                    "message": "Form validation failed",
                    "missing_fields": final_check.get('missing_fields', [])
                }
            
            # Submit form
            submit_result = await self.execute_action({
                "type": "click",
                "selector": form_plan.get("submit_selector"),
                "description": "Submit application form"
            })
            
            if not submit_result:
                return {
                    "status": "error",
                    "message": "Failed to submit form"
                }
            
            # Wait for submission confirmation
            await self.wait_for_page_load()
            
            return {
                "status": "success",
                "message": "Application submitted successfully",
                "submission_date": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error submitting application form: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def get_page_content(self) -> Dict:
        """Extract current page content for AI analysis"""
        try:
            # Ensure page is loaded
            await self.wait_for_page_load()
            
            # Basic page information
            content = {
                'url': self.page.url,
                'title': await self.page.title(),
            }
            
            try:
                # Get page text content
                content['text'] = await self.page.evaluate('''
                    () => document.body ? document.body.innerText : ''
                ''')
            except Exception as e:
                logger.warning(f"Error getting text content: {str(e)}")
                content['text'] = ''

            try:
                # Get page HTML
                content['html'] = await self.page.content()
            except Exception as e:
                logger.warning(f"Error getting HTML content: {str(e)}")
                content['html'] = ''

            try:
                # Get interactive elements
                content['elements'] = await self.page.evaluate('''
                    () => {
                        if (!document.body) return [];
                        const elements = document.querySelectorAll('input, button, a, form');
                        return Array.from(elements).map(el => ({
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            id: el.id || null,
                            name: el.name || null,
                            placeholder: el.placeholder || null,
                            text: el.innerText || null,
                            href: el.href || null,
                            classes: Array.from(el.classList),
                            isVisible: el.offsetParent !== null
                        }));
                    }
                ''')
            except Exception as e:
                logger.warning(f"Error getting elements: {str(e)}")
                content['elements'] = []

            return content
            
        except Exception as e:
            logger.error(f"Error extracting page content: {str(e)}")
            return {
                'url': self.page.url,
                'title': '',
                'text': '',
                'html': '',
                'elements': []
            }

    async def execute_action(self, action: Dict) -> bool:
        """Execute AI-recommended action with enhanced error handling and retries"""
        try:
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    action_type = action.get('type')
                    selector = action.get('selector')
                    value = action.get('value', '')
                    
                    # Wait for element with retry logic
                    if selector:
                        try:
                            element = await self.page.wait_for_selector(
                                selector, 
                                timeout=5000,
                                state='visible'  # Ensure element is visible
                            )
                            if not element:
                                retry_count += 1
                                continue
                        except PlaywrightTimeout:
                            logger.warning(f"Selector timeout: {selector}")
                            retry_count += 1
                            continue
                    
                    if action_type == 'click':
                        # Ensure element is clickable
                        await self.page.wait_for_selector(selector, state='visible')
                        # Scroll element into view
                        await self.page.evaluate(f'document.querySelector("{selector}").scrollIntoView()')
                        await asyncio.sleep(0.5)  # Brief pause after scroll
                        await self.page.click(selector)
                        
                    elif action_type == 'fill':
                        await self.page.fill(selector, value)
                        # Press Tab to trigger any JavaScript events
                        await self.page.press(selector, 'Tab')
                        
                    elif action_type == 'wait':
                        await asyncio.sleep(int(value) if value.isdigit() else 1)
                        
                    elif action_type == 'navigate':
                        await self.page.goto(value)
                        await self.wait_for_page_load()
                        
                    elif action_type == 'select':
                        await self.page.select_option(selector, value)
                        
                    # Wait briefly after any action
                    await asyncio.sleep(0.5)
                    
                    # Wait for any resulting navigation or dynamic content
                    await self.wait_for_page_load()
                    return True
                    
                except PlaywrightTimeout:
                    retry_count += 1
                    logger.warning(f"Action timeout, attempt {retry_count} of {max_retries}")
                    await asyncio.sleep(1)
                    continue
                    
        except Exception as e:
            logger.error(f"Error executing action: {str(e)}")
        return False


    async def search_career_portal(self, company_name: str) -> Dict:
        """Search for company career portal"""
        try:
            # Navigate to Google
            await self.page.goto('https://www.google.com')
            await self.wait_for_page_load()
            
            # Construct search query
            search_query = f"{company_name} careers portal jobs"
            
            try:
                # Type into Google search
                await self.page.fill('textarea[name="q"]', search_query)
                await self.page.press('textarea[name="q"]', 'Enter')
                
                # Wait for results
                await self.page.wait_for_selector('div#search')
                await self.wait_for_page_load()
                
                # Get search results
                results = await self.page.evaluate('''
                    () => {
                        const searchResults = document.querySelectorAll('div.g');
                        return Array.from(searchResults).map(el => ({
                            title: el.querySelector('h3') ? el.querySelector('h3').innerText : '',
                            url: el.querySelector('a') ? el.querySelector('a').href : '',
                            description: el.querySelector('div.VwiC3b') ? 
                                        el.querySelector('div.VwiC3b').innerText : ''
                        })).filter(result => result.url && result.title);
                    }
                ''')
                
                logger.info(f"Found {len(results)} potential career portal results")
                return {"status": "success", "results": results}
                
            except Exception as e:
                logger.error(f"Error during search: {str(e)}")
                return {"status": "error", "message": str(e)}
            
        except Exception as e:
            logger.error(f"Error during career portal search: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def close(self):
        """Close browser instance"""
        if self.browser:
            await self.browser.close()
            logger.info("Browser closed successfully")