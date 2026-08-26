# Udyam MSME State-level extractor
import csv, json, os, random, subprocess, tempfile, time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_URL = "https://api.data.gov.in/resource/8b68ae56-84cf-4728-a0a6-1be11028dea7"
BATCH_SIZE = 10000
MAX_RETRIES = 5
CONNECT_TIMEOUT = 30
MAX_REQUEST_TIME = 300
OUTPUT_ROOT = Path("output")
CHECKPOINT_ROOT = Path("checkpoints")
LOG_ROOT = Path("logs")
CSV_HEADERS = ["LG_ST_Code","State","LG_DT_Code","District","Pincode","RegistrationDate","EnterpriseName","CommunicationAddress","Activities"]

def setup_logger():
    import logging
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    path = LOG_ROOT / f"udyam_{datetime.now():%Y%m%d_%H%M%S}.log"
    logger = logging.getLogger("udyam")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(path, encoding="utf-8"); fh.setFormatter(fmt)
    ch = logging.StreamHandler(); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
    logger.log_file = path
    return logger

def format_elapsed(seconds):
    s = int(seconds); h, r = divmod(s,3600); m, s = divmod(r,60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def get_run_id(): return datetime.now().strftime("%Y-%m-%d")

def checkpoint_path(run_id, state):
    p = CHECKPOINT_ROOT / run_id; p.mkdir(parents=True, exist_ok=True)
    return p / f"{state}.json"

def output_path(run_id, state):
    p = OUTPUT_ROOT / run_id; p.mkdir(parents=True, exist_ok=True)
    return p / f"udyam_msme_{state}.csv"

def load_checkpoint(run_id, state):
    p = checkpoint_path(run_id,state)
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError,OSError): pass
    return {"run_id":run_id,"state":state,"total_records":None,"records_written":0,"last_completed_offset":0,"status":"NOT_STARTED"}

def save_checkpoint(run_id,state,cp):
    cp["updated_at"] = datetime.now().isoformat(timespec="seconds")
    p=checkpoint_path(run_id,state); tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp,indent=4),encoding="utf-8"); tmp.replace(p)

def fetch_batch(api_key,state,offset,logger):
    from urllib.parse import quote
    url=(f"{BASE_URL}?api-key={quote(api_key)}&format=json&offset={offset}"
         f"&limit={BATCH_SIZE}&filters%5BState%5D={quote(state)}")
    for attempt in range(1,MAX_RETRIES+1):
        temp_path=None; started=time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile(delete=False,suffix=".json") as f: temp_path=f.name
            cmd=["curl.exe","-sS","-L","--connect-timeout",str(CONNECT_TIMEOUT),
                 "--max-time",str(MAX_REQUEST_TIME),"-H","accept: application/json",
                 "-o",temp_path,url]
            result=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace")
            elapsed=time.perf_counter()-started
            if result.returncode:
                logger.error("CURL FAILURE | State=%s | Offset=%s | ReturnCode=%s | Elapsed=%s | Error=%s",
                             state,offset,result.returncode,format_elapsed(elapsed),result.stderr.strip())
            else:
                try:
                    data=json.loads(Path(temp_path).read_text(encoding="utf-8"))
                    if data.get("status") == "ok":
                        logger.info("API RESPONSE | State=%s | Offset=%s | Count=%s | Total=%s | Elapsed=%s",
                                    state,offset,data.get("count",0),data.get("total"),format_elapsed(elapsed))
                        return data
                    logger.error("API ERROR | State=%s | Offset=%s | Response=%s",state,offset,json.dumps(data)[:1000])
                except (json.JSONDecodeError,OSError) as exc:
                    logger.error("INVALID API RESPONSE | State=%s | Offset=%s | Error=%s",state,offset,exc)
        finally:
            if temp_path:
                try: os.remove(temp_path)
                except OSError: pass
        if attempt < MAX_RETRIES:
            delay=min(60,5*(2**(attempt-1)))+random.uniform(0,3)
            logger.warning("RETRYING | State=%s | Offset=%s | RetryIn=%.1f seconds",state,offset,delay)
            time.sleep(delay)
    logger.error("API REQUEST FAILED AFTER RETRIES | State=%s | Offset=%s",state,offset)
    return None

def append_records(path,records):
    exists=path.exists() and path.stat().st_size>0
    with path.open("a",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=CSV_HEADERS,extrasaction="ignore")
        if not exists: w.writeheader()
        for r in records: w.writerow({h:r.get(h,"") for h in CSV_HEADERS})
    return len(records)

def extract_state(api_key,state,run_id,logger):
    started=time.perf_counter(); cp=load_checkpoint(run_id,state); out=output_path(run_id,state)
    if cp.get("status")=="COMPLETED":
        logger.info("STATE SKIPPED | State=%s | Status=COMPLETED | Records=%s",state,cp.get("records_written",0)); return cp
    offset=int(cp.get("last_completed_offset",0)); written=int(cp.get("records_written",0)); total=cp.get("total_records")
    if offset and not out.exists(): offset=written=0; total=None
    cp.update({"run_id":run_id,"state":state,"status":"IN_PROGRESS","last_completed_offset":offset,"records_written":written,"total_records":total}); save_checkpoint(run_id,state,cp)
    logger.info("="*80); logger.info("STATE STARTED | State=%s | RunID=%s | ResumeOffset=%s",state,run_id,offset); logger.info("="*80)
    while True:
        batch_start=time.perf_counter(); data=fetch_batch(api_key,state,offset,logger)
        if data is None:
            cp.update({"status":"FAILED","last_completed_offset":offset,"records_written":written,"total_records":total}); save_checkpoint(run_id,state,cp)
            logger.error("STATE FAILED | State=%s | RecordsWritten=%s | LastCompletedOffset=%s | Elapsed=%s",state,written,offset,format_elapsed(time.perf_counter()-started)); return cp
        if total is None: total=int(data.get("total") or 0)
        records=data.get("records") or []; count=len(records)
        if not records:
            cp.update({"status":"COMPLETED","total_records":total,"records_written":written,"last_completed_offset":offset}); save_checkpoint(run_id,state,cp)
            logger.info("STATE COMPLETED | State=%s | Records=%s | Elapsed=%s",state,written,format_elapsed(time.perf_counter()-started)); return cp
        n=append_records(out,records); written+=n; offset+=n
        cp.update({"total_records":total,"records_written":written,"last_completed_offset":offset,"status":"IN_PROGRESS"}); save_checkpoint(run_id,state,cp)
        logger.info("BATCH COMPLETE | State=%s | BatchRecords=%s | Progress=%s/%s | Offset=%s | BatchElapsed=%s",state,n,written,total,offset,format_elapsed(time.perf_counter()-batch_start))
        if (total and written>=total) or count<BATCH_SIZE:
            cp["status"]="COMPLETED"; save_checkpoint(run_id,state,cp)
            logger.info("STATE COMPLETED | State=%s | Records=%s | Elapsed=%s",state,written,format_elapsed(time.perf_counter()-started)); return cp

def extract_states(api_key,states,run_id,logger,max_workers=3):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results=[]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures={ex.submit(extract_state,api_key,s,run_id,logger):s for s in states}
        for f in as_completed(futures):
            state=futures[f]
            try: results.append(f.result())
            except Exception as exc:
                logger.exception("UNHANDLED STATE ERROR | State=%s | Error=%s",state,exc)
                results.append({"state":state,"status":"FAILED","records_written":0})
    return results
