#!/usr/bin/env python3
from mcp_stdio import serve, spec, S, B
from core import Presence

STRINGS={'type':'array','items':S,'maxItems':100}
TOOLS=[
 spec('presence_catalog','Full imported site list, dispositions, known account candidates and exact per-site requirements. Historical candidates are not live authentication.',{'site':S},read=True),
 spec('presence_run','Start or resume the entire user-requested presence job once. Idempotent by task_id. Defaults to all 44 active sites; held/excluded sites stay out. Returns durable run and unfinished requirements.',{'task_id':S,'request':S,'mode':{'type':'string','enum':['execute','draft','audit']},'sites':STRINGS},['task_id','request']),
 spec('presence_status','Read run state, all unfinished requirements and verified post URLs; no publication side effects.',{'run_id':S},read=True),
 spec('presence_amend','Append a user correction without losing the original request or previous requirements.',{'run_id':S,'correction':S},['run_id','correction']),
 spec('presence_next','Lease the next executable site requirement. Other sites continue when one needs recovery. Perform it with native browser tools, record evidence and continue.',{'run_id':S},['run_id']),
 spec('presence_record','Record the actual result of a leased requirement. Verified requires observed readback and evidence URL. This records an agent observation, not an independent provider attestation.',{'task_id':S,'lease':S,'outcome':{'type':'string','enum':['verified','needs_user','waiting_provider','uncertain','retry']},'detail':S,'evidence_url':S,'readback':S},['task_id','lease','outcome','detail']),
 spec('presence_resume_site','Resume a site after observing recovery or reconciling an uncertain action; keeps publication duplicate reservations.',{'run_id':S,'site':S,'evidence':S},['run_id','site','evidence']),
 spec('presence_account','Record the exact identity actually seen in an authenticated browser. Never infer sign-in from an existing tab or old ledger.',{'site':S,'identity':S,'profile_url':S,'browser':{'type':'string','enum':['safari','chrome']},'status':{'type':'string','enum':['signed_in','needs_login','needs_verification']},'evidence':S},['site','identity','profile_url','browser','status','evidence']),
 spec('presence_connections','Read dated account observations. Recheck live identity before publishing.',read=True),
 spec('presence_stage','Stage a distinct post with sources and real media. Rejects common filler, missing media and near-duplicates. Does not replace actual factual/visual inspection.',{'run_id':S,'site':S,'identity':S,'body':S,'angle':S,'sources':{'type':'array','items':{'type':'object','properties':{'claim':S,'url':S},'required':['claim','url'],'additionalProperties':False}},'media_paths':STRINGS},['run_id','site','identity','body','angle','sources','media_paths']),
 spec('presence_review','Bind actual factual and rendered-media inspection to the exact unchanged content hash; this is agent quality review, not another founder approval.',{'content_id':S,'content_hash':S,'factual_evidence':S,'visual_evidence':S,'distinct_reason':S},['content_id','content_hash','factual_evidence','visual_evidence','distinct_reason']),
 spec('presence_prepare_publish','Reserve a duplicate-safe browser publication once, after account and content checks. Returns exact copy/media for native browser execution; DOES NOT itself send a post.',{'content_id':S},['content_id']),
 spec('presence_publication_result','Reconcile submitted content to identity, final text, attachment and permalink. Uncertain outcomes retain duplicate reservations.',{'publication_id':S,'outcome':{'type':'string','enum':['verified','scheduled','uncertain','not_submitted']},'observed_identity':S,'readback':S,'media_verified':B,'url':S},['publication_id','outcome','observed_identity','readback']),
 spec('presence_export','Write a private, hashed run receipt containing remaining requirements and actual publication results.',{'run_id':S},['run_id']),
]
MAPPING={'presence_run':'run','presence_catalog':'catalog','presence_status':'status','presence_amend':'amend','presence_next':'next','presence_record':'record','presence_resume_site':'resume_site','presence_account':'account','presence_connections':'connections','presence_stage':'stage','presence_review':'review','presence_prepare_publish':'prepare','presence_publication_result':'publication_result','presence_export':'export'}
store=None
def dispatch(name,args):
 global store
 if store is None:store=Presence()
 return getattr(store,MAPPING[name])(**args)

if __name__=='__main__':
 serve('black-label-presence',TOOLS,dispatch,'Read the bundled presence skill. One explicit user request covers its full organic scope. This MCP persists scope, quality checks and receipts; black-label-browser performs UI actions. Execute, observe, record, repeat. No duplicate approval prompts. Never fabricate sign-in, publication or provider approval.')
