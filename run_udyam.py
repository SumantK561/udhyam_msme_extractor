# Udyam MSME State-level runner
import os, time
from dotenv import load_dotenv
from udyam_extractor import extract_state, extract_states, format_elapsed, get_run_id, setup_logger

TEST_STATE = "TELANGANA"   # Set to None for all States
MAX_WORKERS = 3

STATES = [
    "ANDAMAN AND NICOBAR ISLANDS","ANDHRA PRADESH","ARUNACHAL PRADESH","ASSAM",
    "BIHAR","CHANDIGARH","CHHATTISGARH","DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
    "DELHI","GOA","GUJARAT","HARYANA","HIMACHAL PRADESH","JAMMU AND KASHMIR",
    "JHARKHAND","KARNATAKA","KERALA","LADAKH","LAKSHADWEEP","MADHYA PRADESH",
    "MAHARASHTRA","MANIPUR","MEGHALAYA","MIZORAM","NAGALAND","ODISHA",
    "PUDUCHERRY","PUNJAB","RAJASTHAN","SIKKIM","TAMIL NADU","TELANGANA",
    "TRIPURA","UTTAR PRADESH","UTTARAKHAND","WEST BENGAL"
]

def main():
    load_dotenv()
    logger=setup_logger(); started=time.perf_counter(); run_id=get_run_id()
    api_key=os.getenv("UDYAM_API_KEY")
    if not api_key:
        logger.error("UDYAM_API_KEY is not configured. Add it to .env")
        raise SystemExit(1)
    states=[TEST_STATE] if TEST_STATE else STATES
    invalid=[s for s in states if s not in STATES]
    if invalid:
        logger.error("Invalid State(s): %s",", ".join(invalid)); raise SystemExit(1)
    logger.info("="*80); logger.info("UDYAM MSME STATE EXTRACTION STARTED")
    logger.info("Run ID=%s | States=%s | MaxWorkers=%s | BatchSize=10000 | TestState=%s",
                run_id,len(states),MAX_WORKERS,TEST_STATE or "ALL")
    if len(states)==1:
        results=[extract_state(api_key,states[0],run_id,logger)]
    else:
        results=extract_states(api_key,states,run_id,logger,MAX_WORKERS)
    elapsed=time.perf_counter()-started
    completed=sum(r.get("status")=="COMPLETED" for r in results)
    failed=sum(r.get("status")=="FAILED" for r in results)
    records=sum(int(r.get("records_written") or 0) for r in results)
    logger.info("="*80); logger.info("FINAL EXECUTION SUMMARY")
    logger.info("Run ID=%s | States Requested=%s | Completed=%s | Failed=%s | Records=%s | Elapsed=%s",
                run_id,len(states),completed,failed,records,format_elapsed(elapsed))
    logger.info("Log file=%s",logger.log_file); logger.info("="*80)
    if failed: logger.warning("Execution completed with %s failed State(s). Re-run to retry/resume.",failed)
    else: logger.info("Execution completed successfully.")

if __name__=="__main__":
    main()
