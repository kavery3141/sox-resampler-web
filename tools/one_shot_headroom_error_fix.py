from pathlib import Path

p=Path('app/static/retry-headroom.js')
s=p.read_text()
repls=[(
"""async function retryHeadroomOptions(jobId){\n  const response=await fetch(`/api/convert/jobs/${jobId}/retry-options`);const data=await response.json();\n  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Unable to determine retry options');\n  return data;\n}\n""",
"""async function retryHeadroomOptions(jobId){\n  const response=await fetch(`/api/convert/jobs/${jobId}/retry-options`);\n  const text=await response.text();let data=null;\n  try{data=text?JSON.parse(text):null}catch(_error){data=null}\n  if(!response.ok){const detail=typeof data?.detail==='string'?data.detail:(text||`Unable to determine retry options (HTTP ${response.status})`);throw new Error(detail)}\n  if(!data||typeof data!=='object')throw new Error('Retry options returned an invalid response');\n  return data;\n}\n"""),(
"""    const response=await fetch(`/api/convert/jobs/${jobId}/retry-headroom-review?${params}`);const review=await response.json();\n    if(!response.ok)throw new Error(typeof review.detail==='string'?review.detail:'Headroom retry review failed');\n""",
"""    const response=await fetch(`/api/convert/jobs/${jobId}/retry-headroom-review?${params}`);\n    const text=await response.text();let review=null;\n    try{review=text?JSON.parse(text):null}catch(_error){review=null}\n    if(!response.ok){const detail=typeof review?.detail==='string'?review.detail:(text||`Headroom retry review failed (HTTP ${response.status})`);throw new Error(detail)}\n    if(!review||typeof review!=='object')throw new Error('Headroom retry review returned an invalid response');\n"""),(
"""    const response=await fetch(`/api/convert/jobs/${jobId}/retry-headroom-start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();\n    if(!response.ok){const detail=typeof data.detail==='string'?data.detail:(data.detail?.blockers||[]).join('; ');throw new Error(detail||'Unable to start headroom retry')}\n    retryHeadroomClose();watchJob(data.job_id,true);\n""",
"""    const response=await fetch(`/api/convert/jobs/${jobId}/retry-headroom-start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});\n    const text=await response.text();let data=null;\n    try{data=text?JSON.parse(text):null}catch(_error){data=null}\n    if(!response.ok){const detail=typeof data?.detail==='string'?data.detail:(Array.isArray(data?.detail?.blockers)?data.detail.blockers.join('; '):(text||`Unable to start headroom retry (HTTP ${response.status})`));throw new Error(detail||'Unable to start headroom retry')}\n    if(!data||!data.job_id)throw new Error('Headroom retry start returned an invalid response');\n    retryHeadroomClose();watchJob(data.job_id,true);\n""")]
for old,new in repls:
    if s.count(old)!=1: raise SystemExit(f'headroom replacement count={s.count(old)}')
    s=s.replace(old,new,1)
p.write_text(s)

p=Path('app/main.py')
s=p.read_text()
needle='''        job_manager.start(new_job_id)\n    except JobError as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    return {\n        "job_id": new_job_id,\n        "status": "running",\n        "retry_with_headroom_of_job_id": job_id,\n        "clipping_failures": len(spec["paths"]),\n        "headroom_db": spec["headroom_db"],\n    }\n'''
replacement='''        job_manager.start(new_job_id)\n    except JobError as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except Exception as exc:\n        record_event(\n            DB_PATH,\n            job_manager._now(),\n            "retry_headroom_start_error",\n            {"source_job_id": job_id, "error_type": type(exc).__name__, "error": str(exc)},\n        )\n        raise HTTPException(\n            status_code=500,\n            detail=f"Headroom retry start failed unexpectedly: {type(exc).__name__}: {exc}",\n        ) from exc\n    return {\n        "job_id": new_job_id,\n        "status": "running",\n        "retry_with_headroom_of_job_id": job_id,\n        "clipping_failures": len(spec["paths"]),\n        "headroom_db": spec["headroom_db"],\n    }\n'''
if s.count(needle)!=1: raise SystemExit(f'backend replacement count={s.count(needle)}')
s=s.replace(needle,replacement,1)
p.write_text(s)
