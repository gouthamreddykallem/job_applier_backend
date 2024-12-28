# main.py

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, List
import logging
from datetime import datetime

from app.core.browser import BrowserAutomation
from app.core.llm import AINavigator
from app.core.job_processor import JobApplicationProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI-Guided Job Application System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
browser_automation = None
ai_navigator = None
job_processor = None

class JobApplication(BaseModel):
    company_name: str
    position_title: str
    location: Optional[str] = None
    resume_path: str
    cover_letter_path: Optional[str] = None
    custom_fields: Optional[Dict] = None
    keywords: Optional[List[str]] = None
    max_applications: Optional[int] = 5

class ApplicationStatus(BaseModel):
    process_id: str

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    try:
        global browser_automation, ai_navigator, job_processor
        
        browser_automation = BrowserAutomation()
        await browser_automation.init_browser()
        
        ai_navigator = AINavigator()
        await ai_navigator.init_model()
        
        job_processor = JobApplicationProcessor(browser_automation, ai_navigator)
        
        logger.info("All services initialized successfully")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    try:
        global browser_automation
        if browser_automation:
            await browser_automation.close()
        logger.info("Services shut down successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")

@app.get("/api/v1/health")
async def health_check():
    """Check system health status"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "browser_automation": "running" if browser_automation else "not_initialized",
            "ai_navigator": "running" if ai_navigator else "not_initialized",
            "job_processor": "running" if job_processor else "not_initialized"
        }
    }

@app.post("/api/v1/applications/batch")
async def submit_batch_applications(application: JobApplication):
    """
    Submit multiple job applications based on criteria
    """
    try:
        if not job_processor:
            raise HTTPException(
                status_code=503,
                detail="Job processor not initialized"
            )

        # Prepare application data
        application_data = {
            "company_name": application.company_name,
            "position_title": application.position_title,
            "location": application.location,
            "resume_path": application.resume_path,
            "cover_letter_path": application.cover_letter_path,
            "custom_fields": application.custom_fields or {},
            "keywords": application.keywords or [],
            "max_applications": application.max_applications
        }

        # Start the batch processing
        result = await job_processor.process_job_applications(application_data)
        
        if result["status"] == "error":
            raise HTTPException(
                status_code=500,
                detail=result["message"]
            )
            
        return {
            "status": "success",
            "process_id": result["process_id"],
            "message": "Batch application process initiated",
            "initial_summary": result["summary"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating batch applications: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.get("/api/v1/applications/batch/{process_id}")
async def get_batch_status(process_id: str):
    """
    Get status of a batch application process
    """
    try:
        if not job_processor:
            raise HTTPException(
                status_code=503,
                detail="Job processor not initialized"
            )

        # Check active applications
        if process_id in job_processor.active_applications:
            return {
                "status": "in_progress",
                "details": job_processor.active_applications[process_id]
            }

        # Get completed and failed applications for this batch
        completed = {
            url: details for url, details in job_processor.completed_applications.items()
            if details.get("batch_id") == process_id
        }
        
        failed = {
            url: details for url, details in job_processor.failed_applications.items()
            if details.get("batch_id") == process_id
        }

        return {
            "status": "completed",
            "summary": {
                "total_completed": len(completed),
                "total_failed": len(failed),
                "completed_applications": [
                    {
                        "job_title": details["job"].title,
                        "company": details["job"].company,
                        "submission_time": details["submission_time"]
                    }
                    for details in completed.values()
                ],
                "failed_applications": [
                    {
                        "job_title": details["job"].title,
                        "company": details["job"].company,
                        "error": details["error"]
                    }
                    for details in failed.values()
                ]
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving batch status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.delete("/api/v1/applications/batch/{process_id}")
async def cancel_batch_process(process_id: str):
    """
    Cancel an ongoing batch application process
    """
    try:
        if not job_processor:
            raise HTTPException(
                status_code=503,
                detail="Job processor not initialized"
            )

        if process_id in job_processor.active_applications:
            job_processor.active_applications[process_id].update({
                "status": "cancelled",
                "end_time": datetime.now().isoformat()
            })
            
            return {
                "status": "success",
                "message": f"Batch process {process_id} cancelled",
                "final_state": job_processor.active_applications[process_id]
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Batch process {process_id} not found or already completed"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling batch process: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# For testing purposes
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)