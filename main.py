import sqlite3
from requests import get, post
from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.status import HTTP_201_CREATED, HTTP_200_OK
import urllib.parse


LINKEDIN_HOST = "https://www.linkedin.com"
LINKEDIN_JOBS_API = LINKEDIN_HOST + "/voyager/api"

app = FastAPI()
templates = Jinja2Templates(directory=".")

# database functions
def get_conn_e_cursor():
    conn = sqlite3.connect("busca_trampo.db")
    return conn, conn.cursor()

def set_up_db():
    conn, cursor = get_conn_e_cursor()
    tables_check = cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name in ('default_settings', 'applied_jobs')")

    if len(tables_check.fetchall()) != 2 :
        cursor.execute("CREATE TABLE default_settings(id, li_at, default_prompt, job_description_queryId)")
        cursor.execute("INSERT INTO default_settings (id, li_at,  default_prompt, job_description_queryId) VALUES (1, '', 'Generate a cover letter for this position', 'voyagerJobsDashJobPostingDetailSections.5b0469809f45002e8d68c712fd6e6285')")
        cursor.execute("CREATE TABLE applied_jobs(id, title, urn, url, company_link)")
        conn.commit()
    conn.close()

def get_li_at(cursor):  
    li_at = cursor.execute("SELECT li_at FROM default_settings").fetchone()

    if li_at is not None:
        return li_at[0]
    else:
        return ''

# Helper class
class BaseJobInfo(BaseModel):
    id: str
    title: str | None = None
    urn: str | None = None
    url: str | None = None
    company_link: str | None = None

class LinkedinJobInfo():
    def __init__(self, element_json, checked_jobs_ids):
        self.title = element_json['jobCardUnion']['jobPostingCard']['title']['text']
        self.jobPostingUrn = element_json['jobCardUnion']['jobPostingCard']['jobPostingUrn']
        self.id = self.jobPostingUrn.split(':')[-1]
        self.url = "https://www.linkedin.com/jobs/view/" + self.id
        self.company_link = element_json['jobCardUnion']['jobPostingCard']['logo'].get('actionTarget')
        self.description = ""
        if self.id in checked_jobs_ids:
            self.checked = True
        else:
            self.checked = False
        checked_jobs_ids.append(self.id)

class DefaultPromptUpdate(BaseModel):
    default_prompt: str

#Helper function
def get_headers(li_at:str, JSESSIONID=''):
    if JSESSIONID == '':
        response = get(
                f'{LINKEDIN_HOST}/jobs/search/', 
                headers={"Cookie":f"li_at={li_at};"}
            )
        JSESSIONID = response.cookies.get('JSESSIONID')

    return {
            "Cookie":f"li_at={li_at}; JSESSIONID={JSESSIONID}",
            "csrf-token":JSESSIONID
        }


set_up_db()


#Endpoints
@app.get("/")
def index_page():
    return FileResponse("index.html")


@app.get("/jobs")
def get_jobs(geoId:str, keywords:str, selectedFilters:str, count=50, start=0, spellCorrectionEnabled="true", JSESSIONID=''):
    conn, cursor = get_conn_e_cursor()
    li_at = get_li_at(cursor)
    applied_jobs = cursor.execute("SELECT id FROM applied_jobs;")
    checked_jobs_ids = [job[0] for job in applied_jobs]
    conn.close()
    headers = get_headers(li_at, JSESSIONID)
    response = get(
            f'{LINKEDIN_JOBS_API}/voyagerJobsDashJobCards?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-220&q=jobSearch&count={count}&query=(origin:JOB_SEARCH_PAGE_JOB_FILTER,keywords:{keywords},locationUnion:(geoId:{geoId}),selectedFilters:{selectedFilters},spellCorrectionEnabled:{spellCorrectionEnabled})&start={start}',
            headers=headers
        )
    all_jobs_info = [LinkedinJobInfo(element, checked_jobs_ids) for element in response.json()['elements'] ]

    filtered_jobs = [job for job in all_jobs_info if not job.checked]

    return JSONResponse({
            "jobs": [job.__dict__ for job in filtered_jobs],
            "search_variables": {
                'geoId':geoId,
                'keywords':keywords,
                'selectedFilters':selectedFilters,
                'count':count,
                'start':start,
                'spellCorrectionEnabled':spellCorrectionEnabled                
            },
            'JSESSIONID':headers["csrf-token"],
            'li_at':li_at
        })


@app.post("/applied")
def mark_applied(job_info: BaseJobInfo):
    conn, cursor = get_conn_e_cursor()
    cursor.execute(f"INSERT INTO applied_jobs (id, title, urn, url, company_link) VALUES ('{job_info.id}','{job_info.title}','{job_info.urn}','{job_info.url}','{job_info.company_link}')")
    conn.commit()
    conn.close()

    return HTTP_201_CREATED

@app.patch("/update_li_at/{li_at}")
def update_li_at(li_at:str):
    conn, cursor = get_conn_e_cursor()
    cursor.execute(f"UPDATE default_settings SET li_at='{li_at}' where id = 1")
    conn.commit()
    conn.close()

    return HTTP_200_OK

@app.patch("/update_default_prompt")
def update_li_at(update: DefaultPromptUpdate):
    conn, cursor = get_conn_e_cursor()
    cursor.execute(f"UPDATE default_settings SET default_prompt='{update.default_prompt.replace("'", "''")}' where id = 1")
    conn.commit()
    conn.close()

    return HTTP_200_OK


@app.get("/job_description/{jobPostingUrn}")
def get_job_description(jobPostingUrn:str, li_at:str, JSESSIONID=''):
    p_jobPostingUrn = urllib.parse.quote_plus(jobPostingUrn)
    conn, cursor = get_conn_e_cursor()
    default_prompt, queryId = cursor.execute(f"SELECT  default_prompt, job_description_queryId FROM default_settings where id = 1").fetchone()
    conn.close()
    description = get(
            f'{LINKEDIN_JOBS_API}/graphql?variables=(cardSectionTypes:List(JOB_DESCRIPTION_CARD),jobPostingUrn:{p_jobPostingUrn})&queryId={queryId}',
            headers=get_headers(li_at, JSESSIONID)
        ).json()

    return JSONResponse({
            "post_date": description['data']['jobsDashJobPostingDetailSectionsByCardSectionTypes']['elements'][0]['jobPostingDetailSection'][0]['jobDescription']['postedOnText'],
            "description": description['data']['jobsDashJobPostingDetailSectionsByCardSectionTypes']['elements'][0]['jobPostingDetailSection'][0]['jobDescription']['jobPosting']['description']['text'],
            "default_prompt": default_prompt
        })
