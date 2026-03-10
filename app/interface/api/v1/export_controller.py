"""Interface layer — FastAPI controller for export endpoints.

Generates XLSX and PPTX exports from dossier data.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from io import BytesIO

from app.interface.auth import AuthUser, Role, get_current_user, require_role


logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/export", tags=["export"])


class ExportRequestSchema(BaseModel):
    request_id: str = Field(..., description="Analysis request ID")
    data: dict = Field(..., description="Full dossier data to export")


@router.post("/xlsx")
async def export_xlsx(
    body: ExportRequestSchema,
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
):
    """Export dossier data as a multi-sheet XLSX workbook."""
    try:
        from app.infrastructure.export.xlsx_generator import generate_dossier_xlsx
        xlsx_bytes = generate_dossier_xlsx(body.data)
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="openpyxl is not installed. Run: pip install openpyxl",
        )
    except Exception as e:
        logger.error("xlsx_export_failed", error=str(e), request_id=body.request_id)
        raise HTTPException(status_code=500, detail=f"XLSX generation failed: {str(e)}")

    entity = body.data.get("entity", "dossier")
    filename = f"{entity}_Research_Report.xlsx"

    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/pptx")
async def export_pptx(
    body: ExportRequestSchema,
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
):
    """Export dossier data as a PPTX presentation."""
    try:
        from app.infrastructure.export.pptx_generator import generate_dossier_pptx
        pptx_bytes = generate_dossier_pptx(body.data)
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="python-pptx is not installed. Run: pip install python-pptx",
        )
    except Exception as e:
        logger.error("pptx_export_failed", error=str(e), request_id=body.request_id)
        raise HTTPException(status_code=500, detail=f"PPTX generation failed: {str(e)}")

    entity = body.data.get("entity", "dossier")
    filename = f"{entity}_Research_Presentation.pptx"

    return StreamingResponse(
        BytesIO(pptx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
