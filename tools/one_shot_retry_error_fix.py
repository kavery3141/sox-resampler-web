from pathlib import Path

# Make retry UI resilient to plain-text/HTML server errors instead of throwing JSON parser noise.
p = Path('app/static/retry-failed.js')
s = p.read_text()
old = """    const response=await fetch(`/api/convert/jobs/${jobId}/retry-review?${params}`);\n    const data=await response.json();\n    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Retry review failed');\n    retryFailedRender(data);\n"""
new = """    const response=await fetch(`/api/convert/jobs/${jobId}/retry-review?${params}`);\n    const text=await response.text();\n    let data=null;\n    try{data=text?JSON.parse(text):null}catch(_error){data=null}\n    if(!response.ok){\n      const detail=typeof data?.detail==='string'?data.detail:(text||`Retry review failed (HTTP ${response.status})`);\n      throw new Error(detail);\n    }\n    if(!data||typeof data!=='object')throw new Error('Retry review returned an invalid response');\n    retryFailedRender(data);\n"""
if s.count(old) != 1:
    raise SystemExit(f'retry review replacement count={s.count(old)}')
s = s.replace(old, new, 1)
old2 = """    const response=await fetch(`/api/convert/jobs/${jobId}/retry-start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workers:Number($('retryFailedWorkers').value||1),source_pre_hash:Boolean($('retryFailedSourcePreHash').checked),acknowledged_replace_in_place:true})});\n    const data=await response.json();\n    if(!response.ok){const detail=typeof data.detail==='string'?data.detail:(data.detail?.blockers||[]).join('; ');throw new Error(detail||'Unable to start retry')}\n    retryFailedClose();watchJob(data.job_id,true);\n"""
new2 = """    const response=await fetch(`/api/convert/jobs/${jobId}/retry-start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workers:Number($('retryFailedWorkers').value||1),source_pre_hash:Boolean($('retryFailedSourcePreHash').checked),acknowledged_replace_in_place:true})});\n    const text=await response.text();\n    let data=null;\n    try{data=text?JSON.parse(text):null}catch(_error){data=null}\n    if(!response.ok){\n      const detail=typeof data?.detail==='string'?data.detail:(Array.isArray(data?.detail?.blockers)?data.detail.blockers.join('; '):(text||`Unable to start retry (HTTP ${response.status})`));\n      throw new Error(detail||'Unable to start retry');\n    }\n    if(!data||!data.job_id)throw new Error('Retry start returned an invalid response');\n    retryFailedClose();watchJob(data.job_id,true);\n"""
if s.count(old2) != 1:
    raise SystemExit(f'retry start replacement count={s.count(old2)}')
s = s.replace(old2, new2, 1)
p.write_text(s)

# Return useful JSON for unexpected retry-start backend exceptions so the UI can show the real cause.
p = Path('app/main.py')
s = p.read_text()
old = """    try:\n        new_job_id = job_manager.create_job(\n            review,\n            spec[\"profile_id\"],\n            request.workers,\n            source_filter,\n            {\"source_pre_hash\": request.source_pre_hash},\n        )\n        job_manager.start(new_job_id)\n    except JobError as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    return {\n        \"job_id\": new_job_id,\n        \"status\": \"running\",\n        \"retry_of_job_id\": job_id,\n        \"failed_files\": len(spec[\"paths\"]),\n    }\n"""
new = """    try:\n        new_job_id = job_manager.create_job(\n            review,\n            spec[\"profile_id\"],\n            request.workers,\n            source_filter,\n            {\"source_pre_hash\": request.source_pre_hash},\n        )\n        job_manager.start(new_job_id)\n    except JobError as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    except Exception as exc:\n        record_event(\n            DB_PATH,\n            job_manager._now(),\n            \"retry_start_error\",\n            {\"source_job_id\": job_id, \"error_type\": type(exc).__name__, \"error\": str(exc)},\n        )\n        raise HTTPException(\n            status_code=500,\n            detail=f\"Retry start failed unexpectedly: {type(exc).__name__}: {exc}\",\n        ) from exc\n    return {\n        \"job_id\": new_job_id,\n        \"status\": \"running\",\n        \"retry_of_job_id\": job_id,\n        \"failed_files\": len(spec[\"paths\"]),\n    }\n"""
if s.count(old) != 1:
    raise SystemExit(f'main retry start replacement count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)
