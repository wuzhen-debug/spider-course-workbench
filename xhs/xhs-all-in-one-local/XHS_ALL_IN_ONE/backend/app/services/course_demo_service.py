"""Idempotent fictional fixtures; writes only new course tables and local files."""
from __future__ import annotations

import hashlib
import unicodedata
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.models.course_center import CourseOffering, CourseMaterialProduct, CourseMaterialVersion, CourseAsset, CourseDemoContent, CourseContentLink


DEMO_FILES = {
    "handout.txt": "课程与资料中心 · 演示文件\n大学与课程均为虚构，仅用于本机功能验收。\nDEMO1000 / 2026S2 / 期末复习讲义 / v1.0\n这里没有真实课程知识、真实品牌或可售资料。\n",
    "sample-watermarked.svg": '''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800" viewBox="0 0 600 800"><rect width="600" height="800" fill="#f3f6fc"/><rect x="32" y="32" width="536" height="736" rx="20" fill="white" stroke="#dae3f3"/><rect x="32" y="32" width="536" height="132" rx="20" fill="#153c75"/><g font-family="sans-serif"><text x="62" y="86" font-size="18" fill="#b8d3ff">FICTIONAL COURSE SAMPLE</text><text x="62" y="128" font-size="30" fill="white">DEMO1000 · 演示讲义</text><text x="62" y="214" font-size="23" fill="#153c75">从课程到资料，再到内容</text><rect x="62" y="245" width="476" height="90" rx="12" fill="#edf3fd"/><text x="84" y="282" font-size="18" fill="#395475">01 课程 / 学期 / 版本</text><text x="84" y="313" font-size="16" fill="#6a7c91">每份资料都有清晰的归属</text><rect x="62" y="360" width="476" height="90" rx="12" fill="#fff1e5"/><text x="84" y="398" font-size="18" fill="#aa591a">02 原件 / 质检 / 样张</text><text x="84" y="429" font-size="16" fill="#8c705b">分别记录，不混淆状态</text><text x="62" y="510" font-size="18" fill="#395475">虚构内容，仅用于界面验收</text><text x="62" y="544" font-size="16" fill="#6a7c91">不是课程成品，也不是正式品牌样张</text><text x="62" y="720" font-size="14" fill="#6a7c91">演示原页码 01 · v1.0</text><text transform="translate(90 635) rotate(-26)" font-size="48" font-weight="bold" fill="#153c75" opacity="0.14">演示样张 · 不用于发布</text></g></svg>''',
    "brand-placeholder.svg": '''<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240" viewBox="0 0 400 240"><rect width="400" height="240" rx="20" fill="#112c52"/><g font-family="sans-serif" text-anchor="middle"><rect x="174" y="32" width="52" height="52" rx="14" fill="#e99c43"/><text x="200" y="68" font-size="28" fill="#112c52">D</text><text x="200" y="128" font-size="27" fill="white">演示品牌占位</text><text x="200" y="166" font-size="17" fill="#afc4e0">不是正式 Logo · 待确认品牌</text><text x="200" y="204" font-size="14" fill="#afc4e0">仅本机演示</text></g></svg>''',
}


def seed_course_demo(db, user_id):
    folder = get_settings().storage_dir / "course-center-demo"
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in DEMO_FILES.items():
        path = folder / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")
    counts = {}
    def seeded(model, key, **values):
        row = db.scalar(select(model).where(model.user_id == user_id, model.seed_key == key))
        if row is None:
            row = model(user_id=user_id, seed_key=key, **values)
            db.add(row); db.flush()
            counts[model.__tablename__] = counts.get(model.__tablename__, 0) + 1
        return row
    courses = []
    for key, uni, term, alias in (("p1-course-a", "演示大学 A（虚构）", "2026S2", "演示课程甲"),
        ("p1-course-b", "演示大学 B（虚构）", "2026S2", "同码不同校"),
        ("p1-course-next-term", "演示大学 A（虚构）", "2027S1", "同课不同学期")):
        courses.append(seeded(CourseOffering, key, university=uni, university_key=unicodedata.normalize("NFKC", uni).casefold(),
            course_code="DEMO1000", code_key="DEMO1000", course_name="课程资料运营演示", term=term, term_key=term,
            aliases=[alias], aliases_search=alias.casefold(), language="中英双语", source_reference="虚构演示数据，不对应真实大学课程", is_demo=True,
            notes="用于验收学校、课程、学期隔离；不会自动触发采集、AI、上传、发布或排期。"))
    course = courses[0]
    product = seeded(CourseMaterialProduct, "p1-product", course_id=course.id, title="期末复习讲义（演示）",
        material_type="期末复习讲义", coverage="演示范围：资料登记、版本区分与内容关联", owner="演示负责人", listing_status="not_listed")
    # Versions can be renamed. The first two rows belong to the original seed
    # transaction (the API never deletes them), so retain their stable IDs.
    versions = list(db.scalars(select(CourseMaterialVersion).where(CourseMaterialVersion.product_id == product.id,
        CourseMaterialVersion.user_id == user_id).order_by(CourseMaterialVersion.id).limit(2)).all())
    fixtures = (("v1.0", "demo://handout.txt", "pending"), ("v0.9", "demo://missing-v0.txt", "changes_required"))
    for label, reference, qa in fixtures[len(versions):]:
        version = db.scalar(select(CourseMaterialVersion).where(CourseMaterialVersion.product_id == product.id, CourseMaterialVersion.version == label, CourseMaterialVersion.language == "中英双语"))
        if version is None:
            version = CourseMaterialVersion(user_id=user_id, product_id=product.id, version=label, source_reference=reference,
                language="中英双语", qa_status=qa, file_status="verified" if label == "v1.0" else "registered",
                sha256=hashlib.sha256((folder / "handout.txt").read_bytes()).hexdigest() if label == "v1.0" else "",
                notes="虚构版本，用于区分文件状态和质检状态。")
            db.add(version); db.flush(); counts[version.__tablename__] = counts.get(version.__tablename__, 0) + 1
        versions.append(version)
    seeded(CourseAsset, "p1-sample", course_id=course.id, version_id=versions[0].id, title="带水印的演示样张",
        asset_kind="sample", reference="demo://sample-watermarked.svg", source_notes="由本机生成的虚构图形，不含真实课程资料。",
        page_reference="演示原页码 01", watermarked=True, rights_confirmed=True, usage_status="pending")
    seeded(CourseAsset, "p1-logo", course_id=course.id, title="品牌占位图（非正式 Logo）", asset_kind="brand_logo",
        reference="demo://brand-placeholder.svg", source_notes="每批真实课程需另行确认品牌与 Logo。", usage_status="pending")
    draft = seeded(CourseDemoContent, "p1-demo-draft", content_kind="draft", title="DEMO1000 资料登记演示草稿",
        body="这是独立演示草稿，未写入原草稿工坊或发布队列。\n用于验证课程、资料版本和内容之间的关联。\n所有大学、课程与资料均为虚构。")
    link = db.scalar(select(CourseContentLink).where(CourseContentLink.user_id == user_id, CourseContentLink.course_id == course.id,
        CourseContentLink.target_kind == "draft", CourseContentLink.target_id == draft.id, CourseContentLink.target_is_demo.is_(True)))
    if link is None:
        db.add(CourseContentLink(user_id=user_id, course_id=course.id, version_id=versions[0].id, target_kind="draft", target_id=draft.id, target_is_demo=True, notes="仅演示关联，不进入真实发布流程。"))
        counts[CourseContentLink.__tablename__] = 1
    return {"course_id": course.id, "created": counts, "created_total": sum(counts.values()), "existing_edits_preserved": True, "external_actions": 0}
