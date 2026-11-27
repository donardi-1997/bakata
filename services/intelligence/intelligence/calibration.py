"""Offline prospective validation; scoring is ordinal, never a probability."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from .storage import instant, ref
from .scoring import RUBRIC_VERSION

WINDOW = timedelta(days=30)
MATURITY = timedelta(days=14)
MIN_SAMPLE = 30
MIN_CLASS = 5
MAX_MEMBERS = 1000
MAX_COHORTS = 100
MAX_MONEY = 10**15


def number(value,lower,upper):
    if type(value) is not int or not lower<=value<=upper:
        raise ValueError("Invalid aggregate outcome")
    return value


def rounded(value):
    return str(value.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP))


class Calibration:
    """Local trusted operator API. No order ingestion, PII or model updates."""
    def __init__(self,archive):
        self.archive=archive
        self.db=archive.db

    def create(self,cohort_id,*,starts_at,minimum_orders,exposure_ref,actor_ref,now):
        cohort_id,exposure_ref,actor_ref=map(ref,(cohort_id,exposure_ref,actor_ref))
        start,now=instant(starts_at),instant(now)
        if not now<start<=now+timedelta(days=30):
            raise ValueError("Register cohort before its observation window")
        number(minimum_orders,1,10000)
        with self.archive.transaction():
            if self.db.execute("SELECT COUNT(*) FROM calibration_cohorts").fetchone()[0]>=MAX_COHORTS:
                raise ValueError("Cohort capacity reached")
            self.db.execute("INSERT INTO calibration_cohorts VALUES (?,?,?,?,?,?,?)",
                            (cohort_id,start.isoformat(),(start+WINDOW).isoformat(),now.isoformat(),
                             minimum_orders,exposure_ref,actor_ref))

    def _cohort(self,cohort_id):
        row=self.db.execute("SELECT starts_at,ends_at,created_at,minimum_orders FROM calibration_cohorts WHERE id=?",
                            (ref(cohort_id),)).fetchone()
        if row is None:
            raise ValueError("Unknown cohort")
        start,end,created,minimum=row
        return datetime.fromisoformat(start),datetime.fromisoformat(end),datetime.fromisoformat(created),minimum

    def enroll(self,cohort_id,product_group,evaluation_id,*,now):
        product_group,evaluation_id=map(ref,(product_group,evaluation_id))
        now=instant(now)
        with self.archive.transaction():
            start,_,created,_=self._cohort(cohort_id)
            if not created<=now<start:
                raise ValueError("Enrollment closed or not yet open")
            record=self.archive.review("evaluation",evaluation_id)
            if record is None:
                raise ValueError("Unknown evaluation")
            result=record["payload"]["result"]
            evaluation_at=datetime.fromisoformat(record["as_of"])
            economics=record["payload"]["economics"]
            if (result["rubric_version"]!=RUBRIC_VERSION or result["status"]!="review-ready"
                or result["coverage_pct"]!=100 or result["blockers"] or result["total"] is None
                or economics is None or economics["currency"]!="COP"):
                raise ValueError("Complete non-blocked COP baseline required")
            if not evaluation_at<=now or start-evaluation_at>timedelta(days=7):
                raise ValueError("Evaluation not available or too old at cohort start")
            observed=datetime.fromisoformat(record["observed_at"])
            age=timedelta(microseconds=result["max_age"])
            review_times=[datetime.fromisoformat(r["reviewed_at"]) for r in record["payload"]["reviews"]]
            review_times.append(datetime.fromisoformat(economics["reviewed_at"]))
            if start-observed>age or any(start-at>age for at in review_times):
                raise ValueError("Baseline evidence expires before cohort starts")
            if self.db.execute("SELECT COUNT(*) FROM calibration_members WHERE cohort_id=?",(cohort_id,)).fetchone()[0]>=MAX_MEMBERS:
                raise ValueError("Cohort member capacity reached")
            self.db.execute("INSERT INTO calibration_members VALUES (?,?,?,?,?,?,?)",
                            (cohort_id,product_group,evaluation_id,record["source"],record["external_id"],
                             now.isoformat(),record["sha256"]))

    def outcome(self,cohort_id,product_group,*,fulfilled_orders,returned_orders,gross_minor,
                contribution_minor,evidence_ref,actor_ref,complete,now):
        product_group,evidence_ref,actor_ref=map(ref,(product_group,evidence_ref,actor_ref))
        now=instant(now)
        if complete is not True:
            raise ValueError("Incomplete outcomes remain missing")
        number(fulfilled_orders,0,1000000)
        number(returned_orders,0,fulfilled_orders)
        number(gross_minor,0,MAX_MONEY)
        number(contribution_minor,-MAX_MONEY,gross_minor)
        if fulfilled_orders==0 and gross_minor!=0:
            raise ValueError("No fulfilled orders cannot have gross sales")
        with self.archive.transaction():
            _,end,_,_=self._cohort(cohort_id)
            if now<end+MATURITY:
                raise ValueError("Outcome window not mature")
            if not self.db.execute("SELECT 1 FROM calibration_members WHERE cohort_id=? AND product_group=?",
                                   (cohort_id,product_group)).fetchone():
                raise ValueError("Outcome must belong to enrolled product")
            self.db.execute("INSERT INTO calibration_outcomes VALUES (?,?,?,?,?,?,?,?,?)",
                            (cohort_id,product_group,now.isoformat(),fulfilled_orders,returned_orders,
                             gross_minor,contribution_minor,evidence_ref,actor_ref))

    def report(self,cohort_id,*,as_of):
        as_of=instant(as_of)
        start,end,created,minimum=self._cohort(cohort_id)
        if as_of<created:
            raise ValueError("Report predates cohort")
        rows=self.db.execute("""SELECT m.product_group,m.evaluation_id,m.evaluation_sha256,m.enrolled_at,
                o.recorded_at,o.fulfilled_orders,o.returned_orders,o.gross_minor,o.contribution_minor
            FROM calibration_members m LEFT JOIN calibration_outcomes o
            ON m.cohort_id=o.cohort_id AND m.product_group=o.product_group
            WHERE m.cohort_id=? ORDER BY m.product_group""",(cohort_id,)).fetchall()
        enrolled=0
        samples=[]
        errors=[]
        bands=[{"range":label,"observed":0,"successes":0} for label in ("0–<25","25–<50","50–<75","75–100")]
        for group,eid,sha,enrolled_at,recorded,orders,returns,gross,contribution in rows:
            if datetime.fromisoformat(enrolled_at)>as_of:
                continue
            enrolled+=1
            if recorded is None or datetime.fromisoformat(recorded)>as_of:
                continue
            record=self.archive.review("evaluation",eid)
            if record is None or record["sha256"]!=sha:
                raise ValueError("Baseline changed after enrollment")
            result=record["payload"]["result"]
            score=Decimal(result["total"])
            success=orders>=minimum and contribution>0
            samples.append((score,success))
            band=bands[min(3,int(score)//25)]
            band["observed"]+=1
            band["successes"]+=int(success)
            if gross>0:
                actual=Decimal(contribution)*100/Decimal(gross)
                errors.append(abs(Decimal(result["margin_pct"])-actual))
        observed=len(samples)
        positives=[s for s,ok in samples if ok]
        negatives=[s for s,ok in samples if not ok]
        ready=(as_of>=end+MATURITY and observed==enrolled and observed>=MIN_SAMPLE
               and min(len(positives),len(negatives))>=MIN_CLASS)
        concordance=None
        if ready:
            twice=sum(2 if p>n else 1 if p==n else 0 for p in positives for n in negatives)
            concordance=rounded(Decimal(twice)*100/(2*len(positives)*len(negatives)))
        for band in bands:
            band["success_rate_pct"]=(rounded(Decimal(band["successes"])*100/band["observed"])
                                     if ready and band["observed"]>=MIN_CLASS else None)
        return {"cohort":cohort_id,"rubric":RUBRIC_VERSION,"as_of":as_of.isoformat(),
                "starts_at":start.isoformat(),"ends_at":end.isoformat(),"minimum_orders":minimum,
                "enrolled":enrolled,"observed":observed,"missing":enrolled-observed,
                "successes":len(positives),"failures":len(negatives),
                "coverage_pct":rounded(Decimal(observed)*100/enrolled) if enrolled else None,
                "status":"descriptive-review-ready" if ready else "insufficient-evidence",
                "rank_concordance_pct":concordance,"bands":bands,
                "margin_error_sample":len(errors),
                "mean_absolute_margin_error_pp":rounded(sum(errors)/len(errors)) if ready and len(errors)>=MIN_SAMPLE else None}
