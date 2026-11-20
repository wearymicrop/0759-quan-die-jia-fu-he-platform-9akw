from fastapi import APIRouter

from app.errors import DomainError
from app.preview import preview
from app.modules.settlement.journal import publish, published, published_all

router = APIRouter()


@router.get('/api/samples/{sample}/settlement')
def settlement_preview(sample: str, order: str | None = None):
    result = preview(sample)['settlement']
    if order is None:
        return result
    for sheet in result['sheets']:
        if sheet['order'] == order:
            return sheet
    raise DomainError('SETTLEMENT_NOT_FOUND', '找不到该复核单', 404)


@router.post('/api/runs/{run_id}/settlements/{settlement_id}/publish')
def publish_sheet(run_id: str, settlement_id: str):
    return publish(run_id, settlement_id)


@router.get('/api/runs/{run_id}/settlements')
def run_settlements(run_id: str):
    return published_all(run_id)


@router.get('/api/runs/{run_id}/settlements/{settlement_id}')
def run_settlement(run_id: str, settlement_id: str):
    return published(run_id, settlement_id)
