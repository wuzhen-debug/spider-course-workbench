import { BookOutlined, CheckCircleOutlined, EditOutlined, FileTextOutlined, LinkOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Descriptions, Drawer, Empty, Form, Input, Modal, Pagination, Popconfirm, Select, Space, Spin, Table, Tabs, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { courseCenterMutation, fetchCourseCapabilities, fetchCourseContentCandidates, fetchCourseDemoImage, fetchCourses, fetchCourseWorkspace } from "../../../lib/api";
import type { Course, CourseAsset, CourseCapabilities, CourseContent, CourseProduct, CourseVersion, CourseWorkspace } from "../../../lib/course-center-types";
import "./course-center.css";
import { CourseLibraryPanel } from "./course-library-panel";

const { Title, Text, Paragraph } = Typography;
const statusLabels: Record<string, [string, string]> = {
  registered: ["已登记 · 未核对", "default"], verified: ["文件已核对", "green"], missing: ["文件未找到", "red"],
  pending: ["待确认", "gold"], passed: ["质检通过", "green"], changes_required: ["待修订", "orange"],
  approved: ["可用于样张", "green"], not_allowed: ["不可使用", "red"],
  not_listed: ["未上架", "default"], listed: ["已登记上架", "blue"], retired: ["已停售", "default"],
  demo_only: ["独立演示草稿", "blue"], published: ["已发布记录", "green"], failed: ["失败记录", "red"],
  saved: ["已入库", "default"], unavailable: ["原内容已不可用", "default"],
};
const materialTypes = ["预习讲义", "学期跟课讲义", "跟课练习", "期中复习讲义", "期末复习讲义", "期中模拟卷", "期末模拟卷", "专项练习与题库", "Cheat Sheet", "Assignment Guide", "答案解析"];
const kindLabels: Record<string, string> = { note: "入库笔记", draft: "草稿", publish_job: "发布历史" };
const fields = {
  course: ["university", "course_code", "course_name", "term", "language", "aliases", "exam_date", "source_reference", "priority", "notes", "is_demo"],
  product: ["title", "material_type", "coverage", "owner", "listing_status", "notes"],
  version: ["version", "language", "source_reference", "sha256", "qa_status", "notes"],
  asset: ["title", "asset_kind", "version_id", "reference", "source_notes", "page_reference", "watermarked", "rights_confirmed", "usage_status"],
  link: ["target_key", "version_id", "notes"],
};
type EditorKind = keyof typeof fields;
type EditorState = { kind: EditorKind; row?: Course | CourseProduct | CourseVersion | CourseAsset; productId?: number };

function Status({ value }: { value: string }) { const [label, color] = statusLabels[value] ?? [value, "default"]; return <Tag color={color}>{label}</Tag>; }
function errorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("；");
  return "操作未完成，请检查本地服务后重试。";
}

function DemoImage({ reference, title }: { reference: string; title: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const name = reference.replace("demo://", "");
    if (!reference.startsWith("demo://") || !["sample-watermarked.svg", "brand-placeholder.svg"].includes(name)) return;
    let cancelled = false; let objectUrl = "";
    void fetchCourseDemoImage(name).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (cancelled) URL.revokeObjectURL(objectUrl); else setUrl(objectUrl);
    }).catch(() => setUrl(""));
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [reference]);
  return <div className="course-preview-frame">{url ? <img src={url} alt={title} /> : <Text type="secondary">仅登记引用，未读取原文件</Text>}</div>;
}

export function CourseCenterPage() {
  return <CourseLibraryPanel />;
}

// Retired workspace retained in source for recovery; no page or navigation mounts it.
function CourseCenterWorkspace({initialCourseId=null,initialQuery=""}:{initialCourseId?:number|null;initialQuery?:string}) {
  const [caps, setCaps] = useState<CourseCapabilities | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState(initialQuery);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(initialCourseId);
  const selectedRef = useRef<number | null>(initialCourseId);
  const listRequest = useRef(0);
  const detailRequest = useRef(0);
  const [workspace, setWorkspace] = useState<CourseWorkspace | null>(null);
  const [realContent, setRealContent] = useState<CourseContent[]>([]);
  const [candidates, setCandidates] = useState<CourseContent[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [preview, setPreview] = useState<CourseContent | null>(null);
  const [form] = Form.useForm<Record<string, unknown>>();
  const course = workspace?.course;
  const products = workspace?.products ?? [];
  const versions = workspace?.versions ?? [];
  const assets = workspace?.assets ?? [];

  function selectCourse(id: number | null) { selectedRef.current = id; setSelectedId(id); }
  async function loadList() {
    const request = ++listRequest.current;
    setLoading(true);
    try {
      const result = await fetchCourses({ q: query, include_archived: includeArchived, page });
      if (request !== listRequest.current) return null;
      setCourses(result.items); setTotal(result.total);
      const nextId = result.items.some((c) => c.id === selectedRef.current) ? selectedRef.current : result.items[0]?.id ?? null;
      selectCourse(nextId);
      return nextId;
    } catch (e) { setError(errorText(e)); return null; } finally { if (request === listRequest.current) setLoading(false); }
  }
  async function loadDetail(id: number) {
    const request = ++detailRequest.current;
    setDetailLoading(true);
    try {
      const result = await fetchCourseWorkspace(id);
      if (request === detailRequest.current && selectedRef.current === id) setWorkspace(result);
    } catch (e) { if (request === detailRequest.current) setError(errorText(e)); } finally { if (request === detailRequest.current) setDetailLoading(false); }
  }
  useEffect(() => {
    void fetchCourseCapabilities().then(setCaps).catch((e) => { setError(errorText(e)); setLoading(false); });
  }, []);
  useEffect(() => { if (caps?.enabled) void loadList(); else if (caps) setLoading(false); }, [caps, query, page, includeArchived]);
  useEffect(() => { if (selectedId) void loadDetail(selectedId); else setWorkspace(null); }, [selectedId]);
  useEffect(() => {
    if (caps?.enabled) void fetchCourseContentCandidates(false).then((r) => setRealContent(r.items)).catch((e) => setError(errorText(e)));
  }, [caps]);

  async function refresh() {
    const id = await loadList(); if (id) await loadDetail(id);
    if (caps?.enabled) {
      try { setRealContent((await fetchCourseContentCandidates(false)).items); } catch (e) { setError(errorText(e)); }
    }
  }
  async function mutate(action: () => Promise<unknown>, text: string) {
    setSaving(true); setError(""); setSuccess("");
    try { await action(); setSuccess(text); await refresh(); } catch (e) { setError(errorText(e)); } finally { setSaving(false); }
  }
  async function seed() {
    await mutate(async () => {
      const result = await courseCenterMutation("demo/seed"); selectCourse(result.course_id);
    }, "演示数据已就绪；重复载入会保留已有编辑，不会新增重复课程。");
  }
  async function openEditor(state: EditorState) {
    setError(""); form.resetFields(); setEditor(state);
    const defaults: Record<string, unknown> = state.kind === "course" ? { term: "2026S2", language: "中英双语", aliases: [], priority: "normal", is_demo: caps?.demo_only ?? true }
      : state.kind === "product" ? { material_type: "期末复习讲义", listing_status: "not_listed" }
      : state.kind === "version" ? { language: "中英双语", qa_status: "pending", source_reference: "", sha256: "" }
      : state.kind === "asset" ? { asset_kind: "sample", usage_status: "pending", watermarked: false, rights_confirmed: false } : {};
    if (state.row) {
      const row = state.row as unknown as Record<string, unknown>;
      for (const key of fields[state.kind]) if (row[key] !== undefined) defaults[key] = row[key];
    }
    form.setFieldsValue(defaults);
    if (state.kind === "link" && course) {
      try { setCandidates((await fetchCourseContentCandidates(course.is_demo)).items); } catch (e) { setError(errorText(e)); }
    }
  }
  async function save(values: Record<string, unknown>) {
    if (!editor) return;
    setSaving(true); setError("");
    try {
      const payload: Record<string, unknown> = {};
      for (const key of fields[editor.kind]) if (values[key] !== undefined) payload[key] = values[key];
      const id = editor.row?.id;
      if (editor.kind === "course") {
        payload.exam_date = payload.exam_date || null;
        payload.is_demo = (editor.row as Course | undefined)?.is_demo ?? (caps?.demo_only ? true : Boolean(payload.is_demo));
        const saved = await courseCenterMutation(id ? `courses/${id}` : "courses", payload, id ? "put" : "post");
        selectCourse(saved.id);
      } else if (editor.kind === "product" && course) {
        await courseCenterMutation(id ? `products/${id}` : `courses/${course.id}/products`, payload, id ? "put" : "post");
      } else if (editor.kind === "version") {
        await courseCenterMutation(id ? `versions/${id}` : `products/${editor.productId}/versions`, payload, id ? "put" : "post");
      } else if (editor.kind === "asset" && course) {
        payload.version_id = payload.version_id || null;
        await courseCenterMutation(id ? `assets/${id}` : `courses/${course.id}/assets`, payload, id ? "put" : "post");
      } else if (editor.kind === "link" && course) {
        const target = candidates.find((c) => `${c.target_kind}:${c.id}` === values.target_key);
        if (!target) throw new Error("请选择内容");
        await courseCenterMutation(`courses/${course.id}/links`, { target_kind: target.target_kind, target_id: target.id,
          target_is_demo: target.target_is_demo, version_id: payload.version_id || null, notes: payload.notes || "" });
      }
      setEditor(null); setSuccess("登记已保存；没有读取或移动原资料，也没有创建发布任务。"); await refresh();
    } catch (e) { setError(errorText(e)); } finally { setSaving(false); }
  }
  const versionOptions = versions.map((v) => ({ value: v.id, label: `${products.find((p) => p.id === v.product_id)?.title ?? "资料"} · ${v.version} · ${v.language}` }));
  const editorTitles = { course: caps?.demo_only ? "演示课程" : "课程", product: "资料产品", version: "资料版本", asset: "样张与品牌", link: "内容关联" };
  const field = (name: string, label: string, required = false, multiline = false, hint?: string) => <Form.Item key={name} name={name} label={label} rules={required ? [{ required: true, whitespace: true, message: `请填写${label}` }] : []} extra={hint}>
    {multiline ? <Input.TextArea rows={3} /> : <Input />}</Form.Item>;

  if (caps && !caps.enabled) return <Card><Empty description="课程与资料中心未启用" /><Paragraph style={{ textAlign: "center" }}>现有小红书功能仍可正常使用。<Link to="/platforms/xhs/dashboard">返回总览</Link></Paragraph></Card>;
  return <div className="course-center">
    <div className="course-hero">
      <Space wrap><Text type="secondary" className="course-eyebrow">COURSE WORKSPACE</Text>{caps?.demo_only && <Tag color="blue">演示模式</Tag>}<Tag>仅本机登记</Tag></Space>
      <Title level={2}>课程与资料中心</Title>
      <Paragraph type="secondary" style={{ marginBottom: 12 }}>按大学、课程与学期整理资料，把版本、样张和内容来源连接起来。</Paragraph>
      <Space wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => void openEditor({ kind: "course" })} disabled={!caps?.enabled}>{caps?.demo_only ? "新建演示课程" : "登记课程"}</Button>
        <Button icon={<BookOutlined />} onClick={() => void seed()} loading={saving} disabled={!caps?.enabled}>{total ? "补齐演示数据" : "载入演示数据"}</Button>
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()} disabled={!caps?.enabled}>刷新</Button>
      </Space>
    </div>
    <Alert type="info" showIcon message={caps?.demo_only ? "虚构课程与演示文件独立保存；本页不调用 AI、发布或自动任务。" : "课程资料与内容关联保存在本机；本页不调用 AI、发布或自动任务。"} style={{ marginBottom: 16 }} />
    {error && <Alert type="error" showIcon message={error} closable onClose={() => setError("")} style={{ marginBottom: 12 }} />}
    {success && <Alert type="success" showIcon message={success} closable onClose={() => setSuccess("")} style={{ marginBottom: 12 }} />}
    <div className="course-metrics">
      {[["课程档案", total], ["当前课程的资料", products.length], ["资料版本", versions.length], ["内容关联", workspace?.links.length ?? 0]].map(([label, value]) => <div className="course-metric" key={label}><Text type="secondary">{label}</Text><strong>{value}</strong></div>)}
    </div>
    <div className="course-layout">
      <aside>
        <Input.Search placeholder="大学、课程代码、别名或学期" defaultValue={initialQuery} allowClear onSearch={(q) => { setQuery(q); setPage(1); }} style={{ marginBottom: 12 }} />
        <Checkbox checked={includeArchived} onChange={(e) => { setIncludeArchived(e.target.checked); setPage(1); }} style={{ marginBottom: 12 }}>包含已归档课程</Checkbox>
        <Spin spinning={loading}>
          <div className="course-list">
            {courses.map((item) => <button key={item.id} className={`course-choice ${item.id === selectedId ? "is-selected" : ""}`} onClick={() => selectCourse(item.id)}>
              <Tag color="blue">{item.term}</Tag>{item.archived && <Tag>已归档</Tag>}
              <small>{item.university}</small><span className="course-code">{item.course_code}</span>
              <Text>{item.course_name}</Text><small>{item.product_count} 项资料 · {item.link_count} 条内容关联</small>
            </button>)}
          </div>
          {!courses.length && !loading && <Card><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? "没有匹配的课程" : "先载入演示数据，或登记第一门课程"} /></Card>}
        </Spin>
        {total > 20 && <Pagination simple pageSize={20} total={total} current={page} onChange={setPage} style={{ marginTop: 16 }} />}
      </aside>
      <div className="course-detail">
        <Spin spinning={detailLoading}>
          {!course ? <Card><Empty description="选择左侧课程查看资料与内容" /></Card> : <>
            <Card className="course-panel" title={<Space wrap><BookOutlined /><span>{course.course_code} · {course.term}</span><Tag>{course.is_demo ? "虚构课程" : "课程档案"}</Tag></Space>}
              extra={<Button size="small" icon={<EditOutlined />} onClick={() => void openEditor({ kind: "course", row: course })}>编辑课程</Button>}>
              <Title level={4} style={{ marginTop: 0 }}>{course.course_name}</Title>
              <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 2 }} items={[
                { key: "university", label: "大学", children: course.university }, { key: "language", label: "语言", children: course.language },
                { key: "aliases", label: "别名", children: course.aliases.length ? course.aliases.map((s) => <Tag key={s}>{s}</Tag>) : "未登记" },
                { key: "exam", label: "考试日期", children: course.exam_date ?? "未登记" },
                { key: "source", label: "来源", span: 2, children: course.source_reference || "未登记" },
              ]} />
              {course.notes && <Paragraph type="secondary" style={{ margin: "12px 0" }}>{course.notes}</Paragraph>}
              <Space wrap><Tag color={course.priority === "high" ? "orange" : "default"}>{({ high: "优先安排", normal: "常规优先级", low: "较低优先级" } as Record<string, string>)[course.priority]}</Tag>
                <Popconfirm title={course.archived ? "恢复这门课程？" : "归档课程？资料和历史都会保留。"} onConfirm={() => mutate(() => courseCenterMutation(`courses/${course.id}/archive`, { archived: !course.archived }, "patch"), course.archived ? "课程已恢复" : "课程已归档，资料和关联历史仍保留")}>
                  <Button type="link" size="small">{course.archived ? "恢复课程" : "归档课程"}</Button>
                </Popconfirm>
              </Space>
            </Card>
            <Tabs items={[
              { key: "materials", label: `资料与版本 (${products.length})`, children: <>
                <Space style={{ marginBottom: 14 }}><Button icon={<PlusOutlined />} onClick={() => void openEditor({ kind: "product" })}>登记资料产品</Button><Text type="secondary">文件、质检与上架状态分别登记</Text></Space>
                {!products.length && <Card><Empty description="尚未登记资料产品" /></Card>}
                {products.map((product) => <Card key={product.id} className="course-panel" title={<Space wrap><FileTextOutlined /><span>{product.title}</span><Tag>{product.material_type}</Tag></Space>}
                  extra={<Button size="small" onClick={() => void openEditor({ kind: "product", row: product })}>编辑</Button>}>
                  <Paragraph type="secondary">{product.coverage || "覆盖范围未登记"}</Paragraph>
                  <Space wrap><Text type="secondary">负责人：{product.owner || "未登记"}</Text><Status value={product.listing_status} /><Text type="secondary">上架状态仅为登记，不会同步网站</Text></Space>
                  <div className="course-status-grid">
                    <div><small>原文件核对</small><Text>{versions.filter((v) => v.product_id === product.id && v.file_status === "verified").length} 个版本已核对</Text></div>
                    <div><small>内容质检</small><Text>{versions.filter((v) => v.product_id === product.id && v.qa_status === "passed").length} 个版本通过</Text></div>
                    <div><small>营销样张</small><Text>{assets.filter((a) => a.asset_kind === "sample" && a.usage_status === "approved" && versions.some((v) => v.product_id === product.id && v.id === a.version_id)).length} 张已确认可用</Text></div>
                  </div>
                  <Table<CourseVersion> size="small" rowKey="id" pagination={false} scroll={{ x: 610 }}
                    dataSource={versions.filter((v) => v.product_id === product.id).sort((a, b) => b.version.localeCompare(a.version, undefined, { numeric: true }))}
                    columns={[
                      { title: "版本", key: "version", width: 120, render: (_, v) => <><Text strong>{v.version}</Text><br /><Text type="secondary">{v.language}</Text></> },
                      { title: "文件与指纹", key: "source", render: (_, v) => <><Status value={v.file_status} /><div className="course-ref">{v.source_reference || "未登记路径"}</div>{v.sha256 && <Text className="course-ref" type="secondary" copyable={{ text: v.sha256 }}>SHA256 {v.sha256.slice(0, 12)}…</Text>}</> },
                      { title: "质检", dataIndex: "qa_status", width: 110, render: (v) => <Status value={v} /> },
                      { title: "操作", key: "actions", width: 100, render: (_, v) => <Space direction="vertical" size={0}><Button type="link" size="small" onClick={() => void openEditor({ kind: "version", row: v })}>编辑版本</Button>{v.source_reference.startsWith("demo://") ? <Button type="link" size="small" loading={saving} onClick={() => mutate(() => courseCenterMutation(`versions/${v.id}/check-file`), "演示文件已核对；质检状态与上架登记保持原样。")}>核对演示文件</Button> : <Text type="secondary">{v.source_reference.startsWith("library://") ? "题库自动核对" : "原文件仅登记"}</Text>}</Space> },
                    ]} />
                  <Button icon={<PlusOutlined />} style={{ marginTop: 14 }} onClick={() => void openEditor({ kind: "version", productId: product.id })}>登记新版本</Button>
                </Card>)}
              </> },
              { key: "assets", label: `样张与品牌 (${assets.length})`, children: <>
                <Button icon={<PlusOutlined />} style={{ marginBottom: 14 }} onClick={() => void openEditor({ kind: "asset" })}>登记样张或品牌素材</Button>
                <div className="course-asset-grid">{assets.map((asset) => <Card key={asset.id} title={asset.title} className="course-panel" extra={<Button size="small" onClick={() => void openEditor({ kind: "asset", row: asset })}>编辑</Button>}>
                  <Space wrap><Tag>{asset.asset_kind === "sample" ? "样张预览" : "品牌 / Logo"}</Tag><Status value={asset.usage_status} /></Space>
                  <DemoImage reference={asset.reference} title={asset.title} />
                  <Paragraph type="secondary">{asset.source_notes || "来源未登记"}</Paragraph>
                  <Space wrap><Tag color={asset.watermarked ? "blue" : "default"}>{asset.watermarked ? "已标记水印" : "未标记水印"}</Tag><Tag>{asset.rights_confirmed ? "使用权已登记确认" : "使用权待确认"}</Tag>{asset.page_reference && <Tag>{asset.page_reference}</Tag>}</Space>
                  <Paragraph className="course-ref" type="secondary" style={{ marginTop: 12 }}>{asset.reference}</Paragraph>
                </Card>)}</div>
                {!assets.length && <Empty description="尚未登记样张与品牌素材" />}
              </> },
              { key: "content", label: `内容关联 (${workspace.links.length})`, children: <>
                <Button icon={<LinkOutlined />} style={{ marginBottom: 14 }} onClick={() => void openEditor({ kind: "link" })}>{course.is_demo ? "关联演示内容" : "关联已有内容"}</Button>
                {!workspace.links.length && <Empty description="当前课程没有关联内容" />}
                {workspace.links.map((link) => <Card key={link.id} className="course-panel" title={link.content.title} extra={<Popconfirm title="取消这条关联？原内容和关联历史都会保留。" onConfirm={() => mutate(() => courseCenterMutation(`links/${link.id}/detach`), "关联已取消，原内容与历史保留")}><Button size="small">取消关联</Button></Popconfirm>}>
                  <Space wrap><Status value={link.content.status} /><Tag>{kindLabels[link.target_kind]}</Tag>{link.version_id && <Tag>{versions.find((v) => v.id === link.version_id)?.version ?? "资料版本不可用"}</Tag>}</Space>
                  <Paragraph style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>{link.content.body}</Paragraph>
                  {link.notes && <Text type="secondary">{link.notes}</Text>}
                  <div style={{ marginTop: 12 }}><Button onClick={() => setPreview(link.content)}>查看内容快照</Button></div>
                </Card>)}
                <Card title="现有内容 · 只读查看" className="course-panel">
                  <Paragraph type="secondary">保留原内容与发布记录。演示课程不会自动关联真实内容，也不会补建已删除的来源草稿。</Paragraph>
                  <Table<CourseContent> size="small" rowKey={(r) => `${r.target_kind}:${r.id}`} pagination={{ pageSize: 5 }} scroll={{ x: 540 }} dataSource={realContent} columns={[
                    { title: "类型", dataIndex: "target_kind", width: 92, render: (kind) => kindLabels[kind] },
                    { title: "标题与来源", key: "title", render: (_, r) => <><Button type="link" style={{ padding: 0, whiteSpace: "normal", textAlign: "left", height: "auto" }} onClick={() => setPreview(r)}>{r.title || "未命名"}</Button>{r.source_hint && <div><Text type="secondary">{r.source_hint}</Text></div>}</> },
                    { title: "状态", dataIndex: "status", width: 115, render: (value) => <Status value={value} /> },
                    { title: "课程关联", dataIndex: "linked_count", width: 90, render: (n) => n ? `${n} 门课程` : <Tag>未关联</Tag> },
                  ]} />
                </Card>
              </> },
            ]} />
          </>}
        </Spin>
      </div>
    </div>
    <Drawer title={editor ? `${editor.row ? "编辑" : "登记"}${editorTitles[editor.kind]}` : "登记"} width={560} open={Boolean(editor)} onClose={() => setEditor(null)}
      extra={<Button type="primary" icon={<CheckCircleOutlined />} loading={saving} onClick={() => form.submit()}>保存登记</Button>}>
      <Alert type="info" message={caps?.demo_only ? "当前只登记演示数据，不触发发布或自动任务。" : "仅保存本机登记，不触发发布或自动任务。"} style={{ marginBottom: 20 }} />
      <Form form={form} layout="vertical" onFinish={(values) => void save(values)}>
        {editor?.kind === "course" && <>
          {!caps?.demo_only && !editor.row && <Form.Item name="is_demo" valuePropName="checked"><Checkbox>这是虚构演示课程</Checkbox></Form.Item>}
          {field("university", "大学名称", true)}{field("course_code", "课程代码", true)}{field("course_name", "课程全称", true)}{field("term", "学期", true)}{field("language", "语言", true)}
          <Form.Item name="aliases" label="课程别名"><Select mode="tags" tokenSeparators={["，", ","]} options={[]} /></Form.Item>
          <Form.Item name="exam_date" label="考试日期"><Input type="date" /></Form.Item>
          <Form.Item name="priority" label="运营优先级"><Select options={[{ value: "high", label: "优先安排" }, { value: "normal", label: "常规" }, { value: "low", label: "较低" }]} /></Form.Item>
          {field("source_reference", "课程来源")}{field("notes", "备注", false, true)}
        </>}
        {editor?.kind === "product" && <>
          {field("title", "资料名称", true)}<Form.Item name="material_type" label="资料类型" rules={[{ required: true }]}><Select options={materialTypes.map((value) => ({ value, label: value }))} /></Form.Item>
          {field("coverage", "覆盖范围", false, true)}{field("owner", "负责人")}
          <Form.Item name="listing_status" label="网站上架登记" extra="仅记录已知状态，不会同步或修改网站。"><Select options={[{ value: "not_listed", label: "未上架" }, { value: "listed", label: "已登记上架" }, { value: "retired", label: "已停售" }]} /></Form.Item>
          {field("notes", "备注", false, true)}
        </>}
        {editor?.kind === "version" && <>
          {field("version", "版本号", true)}{field("language", "语言", true)}{field("source_reference", "原文件或资产引用", false, false, "仅登记；本版只读取受控演示文件，不读取任意路径。")}{field("sha256", "SHA256 指纹")}
          <Form.Item name="qa_status" label="内容质检登记"><Select options={[{ value: "pending", label: "待质检" }, { value: "passed", label: "质检通过" }, { value: "changes_required", label: "待修订" }]} /></Form.Item>
          {field("notes", "版本备注", false, true)}
        </>}
        {editor?.kind === "asset" && <>
          {field("title", "素材名称", true)}<Form.Item name="asset_kind" label="素材类型"><Select options={[{ value: "sample", label: "样张预览" }, { value: "brand_logo", label: "品牌 / Logo" }]} /></Form.Item>
          <Form.Item name="version_id" label="关联资料版本"><Select allowClear options={versionOptions} /></Form.Item>
          {field("reference", "素材引用", false, false, "本地路径或链接仅作登记；演示图片使用 demo:// 引用。")}{field("source_notes", "来源与使用说明", false, true)}{field("page_reference", "原页码")}
          <Form.Item name="watermarked" valuePropName="checked"><Checkbox>样张已带水印</Checkbox></Form.Item>
          <Form.Item name="rights_confirmed" valuePropName="checked"><Checkbox>已确认素材使用权</Checkbox></Form.Item>
          <Form.Item name="usage_status" label="使用状态"><Select options={[{ value: "pending", label: "待确认" }, { value: "approved", label: "可用于样张" }, { value: "not_allowed", label: "不可使用" }]} /></Form.Item>
        </>}
        {editor?.kind === "link" && <>
          <Form.Item name="target_key" label={course?.is_demo ? "选择演示内容" : "选择已有内容"} rules={[{ required: true, message: "请选择内容" }]}><Select options={candidates.map((c) => ({ value: `${c.target_kind}:${c.id}`, label: `${kindLabels[c.target_kind ?? "draft"]} · ${c.title}` }))} /></Form.Item>
          <Form.Item name="version_id" label="关联资料版本"><Select allowClear options={versionOptions} /></Form.Item>{field("notes", "关联说明", false, true)}
        </>}
      </Form>
    </Drawer>
    <Modal open={Boolean(preview)} onCancel={() => setPreview(null)} footer={<Button onClick={() => setPreview(null)}>关闭</Button>} title={preview?.title} width={760}>
      {preview && <><Space><Status value={preview.status} /><Tag>{preview.is_demo ? "独立演示内容" : "现有内容快照"}</Tag></Space><Paragraph style={{ whiteSpace: "pre-wrap", marginTop: 18 }}>{preview.body || "没有正文快照"}</Paragraph>{preview.source_hint && <Alert type="info" message={preview.source_hint} />}</>}
    </Modal>
  </div>;
}
