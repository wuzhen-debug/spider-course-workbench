export type LibraryFile = { id:number; root_id:number; relative_path:string; filename:string; size_bytes:number; mtime_ns:number;
  status:string; error:string; university:string; course_code:string; term:string; material_type:string; classification_status:string;
  classification_reason:string; course_id:number|null; product_id:number|null; current_revision_id:number|null; revision_count:number; first_seen_at:string; updated_at:string };
export type LibraryRevision = { id:number; file_id:number; sha256:string; size_bytes:number; mtime_ns:number; page_count:number|null; pdf_status:string; preview_error:string; version_id:number|null; observed_at:string };
export type LibraryDetail = { file:LibraryFile; revisions:LibraryRevision[]; source_path:string; history_note:string };
export type LibraryStatus = { enabled:boolean; root:{path:string; status:string; watch_backend:string; last_scan_at:string|null; heartbeat_at:string|null; last_error:string}|null;
  counts:Record<string,number>; total:number; products:number; needs_confirmation:number; updated_files:number; watcher_alive:boolean; stable_seconds:number; reconcile_seconds:number };
export type LibraryScope = { scope_university?:string; scope_course?:string; scope_type?:string };
export type LibraryFolder = { value:string; label:string; pending:boolean; file_count:number; child_count:number; error_count:number };
export type LibraryFolderList = { items:LibraryFolder[]; total:number; total_files:number; depth:number; page:number; page_size:number };
export type LibraryDirectoryEntry = {
  name:string; relative_path:string; kind:"directory"|"file"|"symlink"|"other"; is_pdf:boolean; index_eligible:boolean;
  size_bytes:number|null; mtime_ns:number; file_id:number|null; index_status:string|null; can_preview:boolean; revision_count:number; course_initial?:string|null;
};
export type LibraryDirectory = {
  path:string; parent_path:string|null; root_name:string; items:LibraryDirectoryEntry[]; total:number; total_entries:number;
  folder_count:number; file_count:number; pdf_count:number; page:number; page_size:number; synced_at:string; refresh_seconds:number;
  groups:{key:string;label:string;letters:{initial:string;count:number}[];count:number}[];active_group:string;group_target:number;
};
export type LibraryDraftRecipe = { revision_id:number; pages:number[]; mode:"local"|"ai"; instruction:string; brand_id:string };
export type LibraryDraftSource = { filename:string; relative_path:string; university:string; course_code:string; material_type:string; term:string; sha256:string; revision_id:number; page_count:number;
  preview_brand?:{id?:string;name:string;logo_sha256:string;treatment:string}; preview_layout?:string; preview_parent_package_id?:number };
export type LibraryDraftPage = { page:number; text:string; truncated:boolean };
export type LibraryDraftModel = { id:number; name:string; model_name:string; destination:string; configured:boolean };
export type LibraryDraftPlan = { file_id:number; source:LibraryDraftSource; pages:LibraryDraftPage[]; mode:"local"|"ai"; instruction:string; model:LibraryDraftModel|null; warnings:string[]; plan_digest:string };
export type LibraryDraftReview = {
  id:number; file_id:number; revision_id:number; status:"pending"|"saved"; generation_mode:"local"|"ai";
  title:string; body:string; tags:string[]; source:LibraryDraftSource; pages:LibraryDraftPage[];
  model:LibraryDraftModel|Record<string,never>; images:{page:number;sha256:string;width:number;height:number}[];
  source_stale:boolean; warnings:string[]; draft_id:number|null; draft_available?:boolean; created_at:string; reviewed_at:string|null;
  publishing_enabled:false; review_digest:string;
};
