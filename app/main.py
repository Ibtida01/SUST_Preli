from __future__ import annotations

import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.investigator import analyze_ticket_async
from app.models import AnalyzeTicketRequest, AnalyzeTicketResponse, ErrorResponse, HealthResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_COMPLAINT_LENGTH = 2000

app = FastAPI(
    title="QueueStorm Investigator",
    description="AI/API support copilot for digital finance support tickets",
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(detail="Invalid request payload").model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="Internal server error").model_dump(),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post(
    "/analyze-ticket",
    response_model=AnalyzeTicketResponse,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def analyze_ticket_endpoint(payload: AnalyzeTicketRequest) -> AnalyzeTicketResponse | JSONResponse:
    if not payload.complaint.strip():
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(detail="Complaint cannot be empty").model_dump(),
        )

    if len(payload.complaint) > MAX_COMPLAINT_LENGTH:
        payload = payload.model_copy(update={"complaint": payload.complaint[:MAX_COMPLAINT_LENGTH]})

    return await analyze_ticket_async(payload)
