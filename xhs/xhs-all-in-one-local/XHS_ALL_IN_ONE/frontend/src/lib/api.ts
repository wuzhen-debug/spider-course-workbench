import axios from "axios";
import { authFailureMessage, isAuthRejected, isCredentialEndpoint } from "./auth-feedback";
import type { CourseCapabilities, CourseList, CourseWorkspace, CourseContent } from "./course-center-types";
import { message } from "antd";
import type { ResearchContext, ResearchHistory, ResearchMaterial, ResearchWorkspace } from "./course-research-types";

import { fallbackPlatforms } from "./platforms";
import type {
  AuthPayload,
  AutoTask,
  AutoTaskCreatePayload,
  AutoTaskRunResult,
  AutoTaskUpdatePayload,
  AnalyticsCommentInsight,
  AnalyticsHotTopic,
  AnalyticsReportPayload,
  AnalyticsReportResponse,
  AnalyticsTopContent,
  AppNotification,
  BenchmarkCreateDraftsResponse,
  BenchmarkOverview,
  BatchCreateDraftsPayload,
  BatchCreateDraftsResponse,
  BatchTagNotesPayload,
  BatchTagNotesResponse,
  ComposeImagePayload,
  CreateDraftPayload,
  DashboardOverview,
  Draft,
  DescribeImagePayload,
  GenerateNotePayload,
  GenerateCoverPayload,
  GenerateImagePayload,
  GenerateImageResult,
  GeneratedImageAsset,
  GenerateTagsPayload,
  GenerateTitlePayload,
  ImageUtilityFile,
  KeywordGroup,
  KeywordGroupDetail,
  KeywordGroupPayload,
  ModelConfig,
  ModelConfigPayload,
  ModelType,
  MonitoringNote,
  MonitoringRefreshResponse,
  MonitoringSnapshot,
  MonitoringTarget,
  MonitoringTargetPayload,
  NoteAsset,
  NoteComment,
  NotesExportPayload,
  NotesExportResponse,
  Paginated,
  PlatformAccount,
  PlatformMeta,
  PlatformUser,
  PublishAsset,
  PublishAssetPayload,
  PublishJob,
  PublishJobUpdatePayload,
  PolishTextPayload,
  ResizeImagePayload,
  RewriteDraftPayload,
  RunDueTasksResponse,
  SchedulerStatus,
  SavedNote,
  SaveNotesResponse,
  SendDraftToPublishPayload,
  Tag,
  UserImageFile,
  TagPayload,
  TaskRecord,
  XhsNoteSearchResponse,
  XhsDataCrawlItem,
  XhsDataCrawlPayload,
  XhsDataCrawlResponse,
  XhsSearchOptions,
  XhsSearchNote,
  XhsQrLoginSession
} from "../types";

const http = axios.create({
  baseURL: "/api",
  timeout: 120000,
});

export async function xianyuRequest<T>(path:string, data?:unknown, method:'get'|'post'|'patch'='get'):Promise<T> {
  return (await http.request({url:`/platforms/xianyu${path}`,method,data,timeout:120000})).data;
}

export async function xianyuDraftImage(draftId:number,index:number):Promise<Blob> {
  return (await http.get(`/platforms/xianyu/drafts/${draftId}/images/${index}`,{responseType:'blob'})).data;
}

export async function pdfPlatformRequest<T>(path:string,data?:unknown,method:'get'|'post'|'patch'='get'):Promise<T> {
  return (await http.request({url:`/course-center/library${path}`,method,data,timeout:300000})).data;
}
export async function pdfPlatformImage(pairId:number,index:number,version:number):Promise<Blob> {
  return (await http.get(`/course-center/library/platform-drafts/${pairId}/xianyu/images/${index}`,{params:{version},responseType:'blob'})).data;
}

export async function fetchCourseCreations(params:{q?:string;directory?:string;file_id?:number;limit?:number;offset?:number}):Promise<import('./course-creations').CourseCreationList>{
  return (await http.get('/course-center/creations',{params})).data;
}

export async function visualWorkflowGet<T>(path:string,params?:Record<string,unknown>):Promise<T> { return (await http.get(`/course-center/visual-workflows${path}`,{params})).data; }
export async function visualWorkflowAction<T>(path:string,data:unknown,method:'post'|'patch'='post'):Promise<T> { return (await http.request({url:`/course-center/visual-workflows${path}`,method,data,timeout:path.endsWith('/generate-api-images')?900000:path.endsWith('/generate-background')?300000:180000})).data; }
export async function visualWorkflowImage(id:number,assetId:string,source=false):Promise<Blob> { return (await http.get(`/course-center/visual-workflows/${id}/images/${assetId}`,{params:{source},responseType:'blob'})).data; }
export async function visualWorkflowLogo(brandId='xingtu'):Promise<Blob> { return (await http.get('/course-center/visual-workflows/brand/logo',{params:{brand_id:brandId},responseType:'blob'})).data; }
export async function visualWorkflowTemplatePreview(templateId:string):Promise<Blob> { return (await http.get(`/course-center/visual-workflows/template-previews/${encodeURIComponent(templateId)}`,{responseType:'blob'})).data; }

export async function fetchResearchContext(directory: string): Promise<{context:ResearchContext;materials:ResearchMaterial[];suggested_keywords:string[]}> {
  return (await http.get("/course-center/research/context", {params:{library_directory:directory}})).data;
}
export async function fetchResearchHistory(course_code:string,university:string):Promise<{items:ResearchHistory[]}> {
  return (await http.get("/course-center/research",{params:{course_code,university}})).data;
}
export async function fetchResearch(id:number):Promise<ResearchWorkspace> {
  return (await http.get(`/course-center/research/${id}`)).data;
}
export async function researchAction<T>(path:string,data:unknown,method:"post"|"patch"="post"):Promise<T> {
  return (await http.request({url:`/course-center/research${path}`,data,method})).data;
}

// Course registration uses local APIs only; no publishing or AI execution.
export async function fetchCourseCapabilities(): Promise<CourseCapabilities> {
  return (await http.get<CourseCapabilities>("/course-center/capabilities")).data;
}
export async function fetchCourses(params: { q?: string; include_archived?: boolean; page?: number }): Promise<CourseList> {
  return (await http.get<CourseList>("/course-center/courses", { params })).data;
}
export async function fetchCourseWorkspace(id: number): Promise<CourseWorkspace> {
  return (await http.get<CourseWorkspace>(`/course-center/courses/${id}`)).data;
}
export async function courseCenterMutation(path: string, data: unknown = {}, method: "post" | "put" | "patch" = "post") {
  return (await http.request({ url: `/course-center/${path}`, method, data })).data;
}
export async function fetchCourseContentCandidates(demo: boolean): Promise<{ items: CourseContent[]; can_associate: boolean }> {
  return (await http.get("/course-center/content-candidates", { params: { demo } })).data;
}
export async function fetchCourseDemoImage(name: string): Promise<Blob> {
  return (await http.get(`/course-center/demo-assets/${encodeURIComponent(name)}`, { responseType: "blob" })).data;
}

const REFRESH_TOKEN_KEY = "spider_xhs_refresh_token";
let accessToken: string | null = null;
let refreshPromise: Promise<string> | null = null;
let refreshPromiseRevision: number | null = null;
let authRevision = 0;

export type AuthCredentials = {
  username: string;
  password: string;
};

export function getAccessToken(): string | null {
  return accessToken;
}

export function getAuthSessionRevision(): number {
  return authRevision;
}

export function hasRefreshToken(): boolean {
  return Boolean(window.localStorage.getItem(REFRESH_TOKEN_KEY));
}

function getRefreshToken(): string | null {
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

function setAccessToken(token: string | null): void {
  accessToken = token;
}

function persistAuthPayload(payload: AuthPayload): AuthPayload {
  authRevision += 1;
  setAccessToken(payload.access_token);
  if (payload.refresh_token) {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, payload.refresh_token);
  }
  return payload;
}

export function clearAuthTokens(): void {
  authRevision += 1;
  setAccessToken(null);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
}

http.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as typeof error.config & { _authRetry?: boolean; _silent?: boolean };
    if (error.response?.status !== 401 || originalRequest?._authRetry || isCredentialEndpoint(originalRequest?.url) || !getRefreshToken()) {
      if (!originalRequest?._silent) {
        const detail = error.response?.data?.detail;
        const msg = typeof detail === "string" ? detail : "请求失败，请稍后重试";
        message.error(msg);
      }
      return Promise.reject(error);
    }

    originalRequest._authRetry = true;
    const refreshRevision = authRevision;
    try {
      const token = await refreshAccessToken();
      originalRequest.headers.Authorization = `Bearer ${token}`;
      return http(originalRequest);
    } catch (refreshError) {
      if (authRevision === refreshRevision) {
        if (isAuthRejected(refreshError)) clearAuthTokens();
        if (!originalRequest?._silent) message.error(isAuthRejected(refreshError) ? "登录已过期，请重新登录" : authFailureMessage(refreshError, "会话续期暂未完成，请稍后重试。"));
      }
      return Promise.reject(refreshError);
    }
  }
);

export async function login(credentials: AuthCredentials): Promise<AuthPayload> {
  const revision = ++authRevision;
  const response = await http.post<AuthPayload>("/auth/login", credentials, { _silent: true } as object);
  if (authRevision !== revision) throw new Error("Authentication session changed");
  return persistAuthPayload(response.data);
}

export async function register(credentials: AuthCredentials): Promise<AuthPayload> {
  const revision = ++authRevision;
  const response = await http.post<AuthPayload>("/auth/register", credentials, { _silent: true } as object);
  if (authRevision !== revision) throw new Error("Authentication session changed");
  return persistAuthPayload(response.data);
}

export async function refreshAccessToken(): Promise<string> {
  if (refreshPromise && refreshPromiseRevision === authRevision) return refreshPromise;
  const refreshToken = getRefreshToken();
  const refreshRevision = authRevision;
  if (!refreshToken) {
    throw new Error("Missing refresh token");
  }

  const operation = (async () => {
    const response = await http.post<{ access_token: string; token_type: "bearer" }>("/auth/refresh", {
      refresh_token: refreshToken
    }, { _silent: true } as object);
    // A late refresh must not replace a newer login or restore a logged-out session.
    if (getRefreshToken() !== refreshToken || authRevision !== refreshRevision) throw new Error("Authentication session changed");
    setAccessToken(response.data.access_token);
    return response.data.access_token;
  })();
  refreshPromise = operation;
  refreshPromiseRevision = refreshRevision;
  try {
    return await operation;
  } finally {
    if (refreshPromise === operation) {
      refreshPromise = null;
      refreshPromiseRevision = null;
    }
  }
}

export async function fetchMe(): Promise<PlatformUser> {
  const response = await http.get<PlatformUser>("/auth/me");
  return response.data;
}

export async function bootstrapAuth(): Promise<PlatformUser | null> {
  if (!getAccessToken() && hasRefreshToken()) {
    await refreshAccessToken();
  }
  if (!getAccessToken()) {
    return null;
  }
  return fetchMe();
}

export async function logout(): Promise<void> {
  const revision = ++authRevision;
  try {
    await http.post("/auth/logout");
  } finally {
    if (authRevision === revision) clearAuthTokens();
  }
}

export async function fetchPlatforms(): Promise<PlatformMeta[]> {
  try {
    const response = await http.get<Paginated<PlatformMeta>>("/platforms");
    return response.data.items;
  } catch {
    return fallbackPlatforms;
  }
}

export async function fetchXhsOverview(): Promise<DashboardOverview> {
  const response = await http.get<DashboardOverview>("/xhs/analytics/overview");
  return response.data;
}

export async function fetchXhsTopContent(): Promise<{ items: AnalyticsTopContent[] }> {
  const response = await http.get<{ items: AnalyticsTopContent[] }>("/xhs/analytics/top-content");
  return response.data;
}

export async function fetchXhsHotTopics(): Promise<{ items: AnalyticsHotTopic[] }> {
  const response = await http.get<{ items: AnalyticsHotTopic[] }>("/xhs/analytics/hot-topics");
  return response.data;
}

export async function fetchXhsCommentInsights(): Promise<AnalyticsCommentInsight> {
  const response = await http.get<AnalyticsCommentInsight>("/xhs/analytics/comment-insights");
  return response.data;
}

export async function fetchXhsBenchmarks(): Promise<BenchmarkOverview> {
  const response = await http.get<BenchmarkOverview>("/xhs/analytics/benchmarks");
  return response.data;
}

export async function createBenchmarkDrafts(targetId: number, limit = 5): Promise<BenchmarkCreateDraftsResponse> {
  const response = await http.post<BenchmarkCreateDraftsResponse>(
    `/xhs/analytics/benchmarks/${targetId}/create-drafts`,
    null,
    { params: { limit } }
  );
  return response.data;
}

export async function createXhsAnalyticsReport(
  payload: AnalyticsReportPayload = { format: "json" }
): Promise<AnalyticsReportResponse> {
  const response = await http.post<AnalyticsReportResponse>("/xhs/analytics/reports", payload);
  return response.data;
}

export async function fetchAccounts(platform = "xhs"): Promise<PlatformAccount[]> {
  const response = await http.get<Paginated<PlatformAccount>>("/accounts", { params: { platform } });
  return response.data.items;
}

export type SavedNoteFilters = {
  platform?: string;
  q?: string;
  tag_id?: number;
  has_assets?: boolean;
  has_comments?: boolean;
  page_size?: number;
};

export async function fetchSavedNoteIds(platform = "xhs"): Promise<string[]> {
  const response = await http.get<{ items: string[] }>("/notes/ids", { params: { platform } });
  return response.data.items;
}

export async function fetchSavedNotes(platformOrFilters: string | SavedNoteFilters = "xhs"): Promise<Paginated<SavedNote>> {
  const params =
    typeof platformOrFilters === "string"
      ? { platform: platformOrFilters }
      : {
          platform: platformOrFilters.platform ?? "xhs",
          q: platformOrFilters.q || undefined,
          tag_id: platformOrFilters.tag_id,
          has_assets: platformOrFilters.has_assets,
          has_comments: platformOrFilters.has_comments,
          page_size: platformOrFilters.page_size,
        };
  const response = await http.get<Paginated<SavedNote>>("/notes", { params });
  return response.data;
}

export async function fetchSavedNote(noteId: number, silent = false): Promise<SavedNote> {
  const response = await http.get<SavedNote>(`/notes/${noteId}`, { _silent: silent } as never);
  return response.data;
}

export async function fetchSavedNoteAssets(noteId: number): Promise<Paginated<NoteAsset>> {
  const response = await http.get<Paginated<NoteAsset>>(`/notes/${noteId}/assets`);
  return response.data;
}

export async function addNoteAsset(noteId: number, payload: { asset_type: string; url?: string; local_path?: string }): Promise<NoteAsset> {
  const response = await http.post<NoteAsset>(`/notes/${noteId}/assets`, payload);
  return response.data;
}

export async function deleteNoteAsset(noteId: number, assetId: number): Promise<void> {
  await http.delete(`/notes/${noteId}/assets/${assetId}`);
}

export async function reorderNoteAssets(noteId: number, assetIds: number[]): Promise<void> {
  await http.put(`/notes/${noteId}/assets/reorder`, { asset_ids: assetIds });
}

export async function fetchSavedNoteComments(noteId: number, page = 1): Promise<Paginated<NoteComment>> {
  const response = await http.get<Paginated<NoteComment>>(`/notes/${noteId}/comments`, {
    params: { page, page_size: 50 }
  });
  return response.data;
}

export async function deleteSavedNote(noteId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/notes/${noteId}`);
  return response.data;
}

export async function fetchTags(): Promise<Paginated<Tag>> {
  const response = await http.get<Paginated<Tag>>("/tags");
  return response.data;
}

export async function createTag(payload: TagPayload): Promise<Tag> {
  const response = await http.post<Tag>("/tags", payload);
  return response.data;
}

export async function batchTagNotes(payload: BatchTagNotesPayload): Promise<BatchTagNotesResponse> {
  const response = await http.post<BatchTagNotesResponse>("/notes/batch-tag", payload);
  return response.data;
}

export async function batchCreateDraftsFromNotes(
  payload: BatchCreateDraftsPayload
): Promise<BatchCreateDraftsResponse> {
  const response = await http.post<BatchCreateDraftsResponse>("/notes/batch-create-drafts", payload);
  return response.data;
}

export async function exportSavedNotes(payload: NotesExportPayload): Promise<NotesExportResponse> {
  const response = await http.post<NotesExportResponse>("/notes/export", payload);
  return response.data;
}

export async function downloadExportFile(downloadUrl: string, fileName: string): Promise<void> {
  const endpoint = downloadUrl.startsWith("/api") ? downloadUrl.slice(4) : downloadUrl;
  const response = await http.get<Blob>(endpoint, { responseType: "blob" });
  const objectUrl = window.URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(objectUrl);
}

export async function downloadMediaFile(downloadUrl: string, fileName: string): Promise<void> {
  return downloadExportFile(downloadUrl, fileName);
}

export type UploadedFile = {
  file_name: string;
  file_path: string;
  download_url: string;
  asset_type: "image" | "video";
  size: number;
};

export async function uploadAssetFile(file: File): Promise<UploadedFile> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await http.post<UploadedFile>("/files/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return response.data;
}

export async function createMediaObjectUrl(downloadUrl: string): Promise<string> {
  const endpoint = downloadUrl.startsWith("/api") ? downloadUrl.slice(4) : downloadUrl;
  const response = await http.get<Blob>(endpoint, { responseType: "blob" });
  return window.URL.createObjectURL(response.data);
}

export async function searchXhsNotes(payload: XhsSearchOptions): Promise<XhsNoteSearchResponse> {
  const response = await http.post<XhsNoteSearchResponse>("/xhs/pc/search/notes", payload);
  return response.data;
}

export async function crawlXhsDataStream(
  payload: XhsDataCrawlPayload,
  onItem: (index: number, item: XhsDataCrawlItem) => void,
  onProgress?: (message: string) => void,
  onError?: (message: string) => void,
): Promise<{ total: number; success_count: number; failed_count: number }> {
  const token = getAccessToken();
  const response = await fetch("/api/xhs/crawl/data", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || `HTTP ${response.status}`);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response stream");
  const decoder = new TextDecoder();
  let buffer = "";
  let result = { total: 0, success_count: 0, failed_count: 0 };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(line.slice(6));
        if (event.type === "item") onItem(event.index, event.item);
        else if (event.type === "progress") onProgress?.(event.message);
        else if (event.type === "error") onError?.(event.message);
        else if (event.type === "done") result = { total: event.total, success_count: event.success_count, failed_count: event.failed_count };
      } catch { /* skip malformed events */ }
    }
  }
  return result;
}

export async function fetchXhsNoteDetail(payload: { account_id: number; url: string }): Promise<XhsSearchNote> {
  const response = await http.post<XhsSearchNote>("/xhs/pc/notes/detail", payload);
  return response.data;
}

export async function fetchXhsNoteComments(payload: {
  account_id: number;
  note_url: string;
}): Promise<Paginated<NoteComment>> {
  const response = await http.post<{ total: number; items: NoteComment[] }>("/xhs/pc/notes/comments", payload);
  return {
    total: response.data.total,
    page: 1,
    page_size: response.data.items.length,
    items: response.data.items
  };
}

export async function saveXhsNotesToLibrary(payload: {
  account_id: number;
  notes: XhsSearchNote[];
}): Promise<SaveNotesResponse> {
  const response = await http.post<SaveNotesResponse>("/notes/batch-save", payload);
  return response.data;
}

export async function createDraftFromNote(payload: CreateDraftPayload): Promise<Draft> {
  const response = await http.post<Draft>("/drafts", payload);
  return response.data;
}

export async function fetchDrafts(platform = "xhs"): Promise<Paginated<Draft>> {
  const response = await http.get<Paginated<Draft>>("/drafts", { params: { platform } });
  return response.data;
}

export async function updateDraft(draftId: number, payload: { title?: string; body?: string; tags?: { id?: string; name: string }[] }): Promise<Draft> {
  const response = await http.patch<Draft>(`/drafts/${draftId}`, payload);
  return response.data;
}

export async function fetchDraft(draftId: number): Promise<Draft> {
  return (await http.get<Draft>(`/drafts/${draftId}`)).data;
}

export async function deleteDraft(draftId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/drafts/${draftId}`);
  return response.data;
}

export type DraftAsset = {
  id: number;
  draft_id: number;
  asset_type: "image" | "video" | string;
  url: string;
  local_path: string;
  sort_order: number;
};

export async function fetchDraftAssets(draftId: number): Promise<{ items: DraftAsset[] }> {
  const response = await http.get<{ items: DraftAsset[] }>(`/drafts/${draftId}/assets`);
  return response.data;
}

export async function addDraftAsset(draftId: number, payload: { asset_type: string; url?: string; local_path?: string }): Promise<DraftAsset> {
  const response = await http.post<DraftAsset>(`/drafts/${draftId}/assets`, payload);
  return response.data;
}

export async function deleteDraftAsset(draftId: number, assetId: number): Promise<void> {
  await http.delete(`/drafts/${draftId}/assets/${assetId}`);
}

export async function addDraftImageVariant(draftId: number, assetId: number, url: string): Promise<{items:DraftAsset[]}> {
  const response = await http.post<{items:DraftAsset[]}>(`/drafts/${draftId}/assets/${assetId}/variants`, {url});
  return response.data;
}

export async function updateDraftAsset(draftId: number, assetId: number, payload: { url?: string; local_path?: string }): Promise<DraftAsset> {
  const response = await http.patch<DraftAsset>(`/drafts/${draftId}/assets/${assetId}`, payload);
  return response.data;
}

export async function reorderDraftAssets(draftId: number, assetIds: number[]): Promise<void> {
  await http.put(`/drafts/${draftId}/assets/reorder`, { asset_ids: assetIds });
}

export async function sendDraftToPublish(draftId: number, payload: SendDraftToPublishPayload): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/drafts/${draftId}/send-to-publish`, payload);
  return response.data;
}

export async function rewriteDraftWithAi(payload: RewriteDraftPayload): Promise<Draft> {
  const response = await http.post<Draft>("/ai/rewrite-note", payload);
  return response.data;
}

export async function generateNoteWithAi(payload: GenerateNotePayload): Promise<Draft> {
  const response = await http.post<Draft>("/ai/generate-note", payload);
  return response.data;
}

export async function generateTitleOptions(payload: GenerateTitlePayload): Promise<{ items: string[] }> {
  const response = await http.post<{ items: string[] }>("/ai/generate-title", payload);
  return response.data;
}

export async function generateTagOptions(payload: GenerateTagsPayload): Promise<{ items: string[] }> {
  const response = await http.post<{ items: string[] }>("/ai/generate-tags", payload);
  return response.data;
}

export async function polishTextWithAi(payload: PolishTextPayload): Promise<{ text: string }> {
  const response = await http.post<{ text: string }>("/ai/polish-text", payload);
  return response.data;
}

export async function fetchGeneratedImageAssets(): Promise<Paginated<GeneratedImageAsset>> {
  const response = await http.get<Paginated<GeneratedImageAsset>>("/ai/images/assets");
  return response.data;
}

export async function deleteGeneratedImageAsset(assetId: number): Promise<void> {
  await http.delete(`/ai/images/assets/${assetId}`);
}

export async function deleteUserImage(fileName: string): Promise<void> {
  await http.delete(`/files/images/${fileName}`);
}

export async function generateCoverWithAi(payload: GenerateCoverPayload): Promise<GeneratedImageAsset> {
  const response = await http.post<GeneratedImageAsset>("/ai/images/generate-cover", payload);
  return response.data;
}

export async function generateImageWithAi(payload: GenerateImagePayload): Promise<GenerateImageResult> {
  const response = await http.post<GenerateImageResult>("/ai/images/generate", payload, { timeout: 180000 });
  return response.data;
}

export async function fetchUserImages(): Promise<{ items: UserImageFile[] }> {
  const response = await http.get<{ items: UserImageFile[] }>("/files/images");
  return response.data;
}

export async function describeImageWithAi(payload: DescribeImagePayload): Promise<{ text: string }> {
  const response = await http.post<{ text: string }>("/ai/images/describe", payload);
  return response.data;
}

export async function composeImageUtility(payload: ComposeImagePayload): Promise<ImageUtilityFile> {
  const response = await http.post<ImageUtilityFile>("/files/images/compose", payload);
  return response.data;
}

export async function resizeImageUtility(payload: ResizeImagePayload): Promise<ImageUtilityFile> {
  const response = await http.post<ImageUtilityFile>("/files/images/resize", payload);
  return response.data;
}

export async function fetchModelConfigs(modelType?: ModelType): Promise<Paginated<ModelConfig>> {
  const response = await http.get<Paginated<ModelConfig>>("/model-configs", {
    params: modelType ? { model_type: modelType } : undefined
  });
  return response.data;
}

export async function createModelConfig(payload: ModelConfigPayload): Promise<ModelConfig> {
  const response = await http.post<ModelConfig>("/model-configs", payload);
  return response.data;
}

export async function setDefaultModelConfig(configId: number): Promise<ModelConfig> {
  const response = await http.post<ModelConfig>(`/model-configs/${configId}/set-default`);
  return response.data;
}

export async function updateModelConfig(configId: number, payload: Partial<ModelConfigPayload>): Promise<ModelConfig> {
  const response = await http.patch<ModelConfig>(`/model-configs/${configId}`, payload);
  return response.data;
}

export async function testModelConfig(configId: number): Promise<{ id: number; status: string; message: string; image_url?: string }> {
  const response = await http.post<{ id: number; status: string; message: string; image_url?: string }>(`/model-configs/${configId}/test`,undefined,{timeout:190_000});
  return response.data;
}

export async function deleteModelConfig(configId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/model-configs/${configId}`);
  return response.data;
}

export async function fetchTasks(platform?: string): Promise<Paginated<TaskRecord>> {
  const response = await http.get<Paginated<TaskRecord>>("/tasks", {
    params: platform ? { platform } : undefined
  });
  return response.data;
}

export async function fetchSchedulerStatus(): Promise<SchedulerStatus> {
  const response = await http.get<SchedulerStatus>("/tasks/scheduler/status");
  return response.data;
}

export async function cancelTask(taskId: number): Promise<TaskRecord> {
  const response = await http.post<TaskRecord>(`/tasks/${taskId}/cancel`);
  return response.data;
}

export async function retryTask(taskId: number): Promise<TaskRecord> {
  const response = await http.post<TaskRecord>(`/tasks/${taskId}/retry`);
  return response.data;
}

export async function runDueTasks(platform = "xhs"): Promise<RunDueTasksResponse> {
  const response = await http.post<RunDueTasksResponse>("/tasks/run-due", null, { params: { platform } });
  return response.data;
}

export async function fetchMonitoringTargets(): Promise<Paginated<MonitoringTarget>> {
  const response = await http.get<Paginated<MonitoringTarget>>("/xhs/monitoring/targets");
  return response.data;
}

export async function createMonitoringTarget(payload: MonitoringTargetPayload): Promise<MonitoringTarget> {
  const response = await http.post<MonitoringTarget>("/xhs/monitoring/targets", payload);
  return response.data;
}

export async function updateMonitoringTarget(
  targetId: number,
  payload: Partial<MonitoringTargetPayload>
): Promise<MonitoringTarget> {
  const response = await http.patch<MonitoringTarget>(`/xhs/monitoring/targets/${targetId}`, payload);
  return response.data;
}

export async function deleteMonitoringTarget(targetId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/xhs/monitoring/targets/${targetId}`);
  return response.data;
}

export async function refreshMonitoringTarget(targetId: number): Promise<MonitoringRefreshResponse> {
  const response = await http.post<MonitoringRefreshResponse>(`/xhs/monitoring/targets/${targetId}/refresh`);
  return response.data;
}

export async function fetchMonitoringSnapshots(targetId: number): Promise<{ target_id: number; items: MonitoringSnapshot[] }> {
  const response = await http.get<{ target_id: number; items: MonitoringSnapshot[] }>(
    `/xhs/monitoring/targets/${targetId}/snapshots`
  );
  return response.data;
}

export async function fetchMonitoringTargetNotes(targetId: number): Promise<{ target_id: number; items: MonitoringNote[] }> {
  const response = await http.get<{ target_id: number; items: MonitoringNote[] }>(
    `/xhs/monitoring/targets/${targetId}/notes`
  );
  return response.data;
}

export async function fetchKeywordGroups(platform = "xhs"): Promise<Paginated<KeywordGroup>> {
  const response = await http.get<Paginated<KeywordGroup>>("/keyword-groups", { params: { platform } });
  return response.data;
}

export async function createKeywordGroup(payload: KeywordGroupPayload): Promise<KeywordGroup> {
  const response = await http.post<KeywordGroup>("/keyword-groups", payload);
  return response.data;
}

export async function fetchKeywordGroup(groupId: number): Promise<KeywordGroupDetail> {
  const response = await http.get<KeywordGroupDetail>(`/keyword-groups/${groupId}`);
  return response.data;
}

export async function updateKeywordGroup(
  groupId: number,
  payload: Partial<KeywordGroupPayload>
): Promise<KeywordGroup> {
  const response = await http.patch<KeywordGroup>(`/keyword-groups/${groupId}`, payload);
  return response.data;
}

export async function deleteKeywordGroup(groupId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/keyword-groups/${groupId}`);
  return response.data;
}

export async function fetchPublishJobs(platform = "xhs"): Promise<Paginated<PublishJob>> {
  const response = await http.get<Paginated<PublishJob>>("/publish/jobs", { params: { platform } });
  return response.data;
}

export async function fetchPublishJob(jobId: number): Promise<PublishJob> {
  const response = await http.get<PublishJob>(`/publish/jobs/${jobId}`);
  return response.data;
}

export async function updatePublishJob(jobId: number, payload: PublishJobUpdatePayload): Promise<PublishJob> {
  const response = await http.patch<PublishJob>(`/publish/jobs/${jobId}`, payload);
  return response.data;
}

export async function publishJobToCreator(jobId: number): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/publish/jobs/${jobId}/publish`);
  return response.data;
}

export async function retryPublishJob(jobId: number): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/publish/jobs/${jobId}/retry`);
  return response.data;
}

export async function cancelPublishJob(jobId: number): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/publish/jobs/${jobId}/cancel`);
  return response.data;
}

export async function deletePublishJob(jobId: number): Promise<void> {
  await http.delete(`/publish/jobs/${jobId}`);
}

export async function fetchPublishAssets(jobId: number): Promise<Paginated<PublishAsset>> {
  const response = await http.get<Paginated<PublishAsset>>(`/publish/jobs/${jobId}/assets`);
  return response.data;
}

export async function addPublishAsset(jobId: number, payload: PublishAssetPayload): Promise<PublishAsset> {
  const response = await http.post<PublishAsset>(`/publish/jobs/${jobId}/assets`, payload);
  return response.data;
}

export async function deletePublishAsset(assetId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/publish/assets/${assetId}`);
  return response.data;
}

export async function uploadPublishAsset(assetId: number): Promise<PublishAsset> {
  const response = await http.post<PublishAsset>(`/publish/assets/${assetId}/upload`);
  return response.data;
}

export async function importXhsCookieAccount(payload: {
  sub_type: "pc" | "creator";
  cookie_string: string;
  sync_creator?: boolean;
}): Promise<PlatformAccount> {
  const response = await http.post<PlatformAccount>("/accounts/import-cookie", {
    platform: "xhs",
    ...payload
  });
  return response.data;
}

export async function checkAccount(accountId: number): Promise<PlatformAccount> {
  const response = await http.post<PlatformAccount>(`/accounts/${accountId}/check`);
  return response.data;
}

export type CreatorSessionCheck = {
  account_id: number;
  checked_at: string;
  session_ok: boolean;
  publish_permission: "not_tested";
  message: string;
  account_name?: string;
  repair?: {requires_pc_login:boolean;matching_pc_account_id:number|null};
};

export async function checkCreatorPublishSession(accountId: number): Promise<CreatorSessionCheck> {
  const response = await http.post<CreatorSessionCheck>(`/accounts/${accountId}/check-publish-session`);
  return response.data;
}

export async function repairCreatorPublishSession(accountId:number):Promise<CreatorSessionCheck>{
  return (await http.post<CreatorSessionCheck>(`/accounts/${accountId}/repair-publish-session`)).data;
}

export type CreatorVerification = {
  job_id: number;
  account_id?: number;
  account_name?: string;
  task_id?: number;
  state: "not_required" | "legacy_missing" | "available" | "expired" | "unavailable" | "reported_verified";
  verification_type?: string;
  method?: "qr_code";
  official_url?: string | null;
  message?: string;
  automatic_retry: false;
  will_publish: false;
  expires_in_seconds?: number;
};

export async function fetchCreatorVerification(jobId: number): Promise<CreatorVerification> {
  const response = await http.get<CreatorVerification>(`/publish/jobs/${jobId}/verification`);
  return response.data;
}

export async function acknowledgeCreatorVerification(jobId: number, taskId: number): Promise<CreatorVerification> {
  const response = await http.post<CreatorVerification>(`/publish/jobs/${jobId}/verification/acknowledge`, {task_id: taskId});
  return response.data;
}

export async function downloadOfficialPublishPackage(jobId: number, topics: string[]): Promise<void> {
  try {
    const response = await http.post<Blob>(`/publish/jobs/${jobId}/official-package`, {topics}, {responseType:"blob"});
    const url = URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = url; link.download = `xhs-note-${jobId}.zip`;
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  } catch (e: unknown) {
    const data = (e as {response?:{data?:Blob}})?.response?.data;
    if (data instanceof Blob) {
      let detail: unknown;
      try { detail = JSON.parse(await data.text()).detail; } catch { /* retain generic fallback */ }
      if (typeof detail === "string") throw new Error(detail);
    }
    throw new Error("准备包下载失败，请检查本机服务后重试。");
  }
}

export async function deleteAccount(accountId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/accounts/${accountId}`);
  return response.data;
}

export async function createXhsPcQrLoginSession(payload?: {
  sync_creator?: boolean;
  target_creator_account_id?:number;
}): Promise<XhsQrLoginSession> {
  const response = await http.post<XhsQrLoginSession>("/xhs/login-sessions/pc/qrcode", payload ?? {}, { _silent: true } as import("axios").AxiosRequestConfig);
  return response.data;
}

export async function createXhsCreatorQrLoginSession(): Promise<XhsQrLoginSession> {
  const response = await http.post<XhsQrLoginSession>("/xhs/login-sessions/creator/qrcode", undefined, { _silent: true } as import("axios").AxiosRequestConfig);
  return response.data;
}

export async function pollXhsLoginSession(sessionId: number): Promise<XhsQrLoginSession> {
  const response = await http.get<XhsQrLoginSession>(`/xhs/login-sessions/${sessionId}`, { _silent: true } as import("axios").AxiosRequestConfig);
  return response.data;
}

export async function sendXhsPhoneCode(payload: {
  sub_type: "pc" | "creator";
  phone: string;
  sync_creator?: boolean;
}): Promise<{ session_id: number; status: string; message: string }> {
  const response = await http.post<{ session_id: number; status: string; message: string }>(
    `/xhs/login-sessions/${payload.sub_type}/phone/send-code`,
    { phone: payload.phone, sync_creator: payload.sync_creator },
    { _silent: true } as import("axios").AxiosRequestConfig
  );
  return response.data;
}

export async function confirmXhsPhoneLogin(payload: {
  sub_type: "pc" | "creator";
  session_id: number;
  phone: string;
  code: string;
  sync_creator?: boolean;
}): Promise<XhsQrLoginSession> {
  const response = await http.post<XhsQrLoginSession>(`/xhs/login-sessions/${payload.sub_type}/phone/confirm`, {
    session_id: payload.session_id,
    phone: payload.phone,
    code: payload.code,
    sync_creator: payload.sync_creator
  }, { _silent: true } as import("axios").AxiosRequestConfig);
  return response.data;
}

export async function fetchNotifications(params?: { unread?: boolean; page?: number; page_size?: number }): Promise<Paginated<AppNotification>> {
  const response = await http.get<Paginated<AppNotification>>("/notifications", { params });
  return response.data;
}

export async function markNotificationRead(id: number): Promise<AppNotification> {
  const response = await http.post<AppNotification>(`/notifications/${id}/read`);
  return response.data;
}

export async function markAllNotificationsRead(): Promise<{ marked: number }> {
  const response = await http.post<{ marked: number }>("/notifications/read-all");
  return response.data;
}

// Auto Tasks (Auto Operations)

export async function fetchAutoTasks(): Promise<Paginated<AutoTask>> {
  const response = await http.get<Paginated<AutoTask>>("/auto-tasks");
  return response.data;
}

export async function createAutoTask(payload: AutoTaskCreatePayload): Promise<AutoTask> {
  const response = await http.post<AutoTask>("/auto-tasks", payload);
  return response.data;
}

export async function updateAutoTask(taskId: number, payload: AutoTaskUpdatePayload): Promise<AutoTask> {
  const response = await http.patch<AutoTask>(`/auto-tasks/${taskId}`, payload);
  return response.data;
}

export async function deleteAutoTask(taskId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/auto-tasks/${taskId}`);
  return response.data;
}

export async function runAutoTask(taskId: number): Promise<AutoTaskRunResult> {
  const response = await http.post<AutoTaskRunResult>(`/auto-tasks/${taskId}/run`);
  return response.data;
}
export async function fetchLibraryStatus(): Promise<import("./course-library-types").LibraryStatus> { return (await http.get("/course-center/library/status")).data; }
export async function fetchLibraryFiles(params: import("./course-library-types").LibraryScope & { q?:string; university?:string; state?:string; page?:number; directory_path?:string }) {
  return (await http.get<{items:import("./course-library-types").LibraryFile[];total:number;page:number;page_size:number}>("/course-center/library/files",{params})).data;
}
export async function fetchLibraryFolders(params: import("./course-library-types").LibraryScope & { state?:string; folder_q?:string; page?:number }): Promise<import("./course-library-types").LibraryFolderList> {
  return (await http.get("/course-center/library/folders",{params})).data;
}
export async function fetchLibraryUniversities(): Promise<string[]> { return (await http.get("/course-center/library/universities")).data.items; }
export async function fetchLibraryDetail(id:number): Promise<import("./course-library-types").LibraryDetail> { return (await http.get(`/course-center/library/files/${id}`)).data; }
export async function fetchLibraryPreview(id:number,page:number,revisionId:number): Promise<Blob> {
  return (await http.get(`/course-center/library/files/${id}/preview`,{params:{page,revision_id:revisionId},responseType:"blob"})).data;
}
export async function requestLibraryRescan() { return (await http.post("/course-center/library/rescan")).data; }
export async function fetchLibraryDirectory(params:{path:string;q?:string;page?:number;alphabetic?:boolean;group_key?:string}):Promise<import("./course-library-types").LibraryDirectory> {
  return (await http.get("/course-center/library/directory",{params})).data;
}
export async function prepareLibraryDraft(fileId:number,recipe:import("./course-library-types").LibraryDraftRecipe):Promise<import("./course-library-types").LibraryDraftPlan> {
  return (await http.post(`/course-center/library/files/${fileId}/draft-plan`,recipe,{timeout:60000})).data;
}
export async function generateLibraryDraft(fileId:number,recipe:import("./course-library-types").LibraryDraftRecipe & {plan_digest:string;request_key:string;external_consent:boolean}):Promise<import("./course-library-types").LibraryDraftReview> {
  return (await http.post(`/course-center/library/files/${fileId}/drafts`,recipe,{timeout:240000})).data;
}
export async function fetchLibraryDraftHistory(fileId:number):Promise<import("./course-library-types").LibraryDraftReview[]> { return (await http.get(`/course-center/library/files/${fileId}/drafts`)).data.items; }
export async function fetchLibraryDraftReview(id:number):Promise<import("./course-library-types").LibraryDraftReview> { return (await http.get(`/course-center/library/draft-reviews/${id}`)).data; }
export async function fetchLibraryDraftImage(id:number,index:number):Promise<Blob> { return (await http.get(`/course-center/library/draft-reviews/${id}/images/${index}`,{responseType:"blob"})).data; }
export async function saveLibraryDraftReview(id:number,payload:{title:string;body:string;tags:string[]}):Promise<import("./course-library-types").LibraryDraftReview> { return (await http.patch(`/course-center/library/draft-reviews/${id}`,payload)).data; }
export async function reframeLibraryDraftReview(id:number,payload:{title:string;body:string;tags:string[];request_key:string}):Promise<import("./course-library-types").LibraryDraftReview> { return (await http.post(`/course-center/library/draft-reviews/${id}/reframe`,payload)).data; }
export async function approveLibraryDraftReview(id:number,reviewDigest:string):Promise<import("./course-library-types").LibraryDraftReview> { return (await http.post(`/course-center/library/draft-reviews/${id}/approve`,{reviewed:true,review_digest:reviewDigest})).data; }
