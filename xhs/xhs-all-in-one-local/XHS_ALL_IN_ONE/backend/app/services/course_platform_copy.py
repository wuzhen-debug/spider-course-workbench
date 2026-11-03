"""Product copy from PDF evidence, independently of the Xiaohongshu note text."""
import re


def product_copy(source,pages):
    course=source.get('course_code') or '课程待核对'
    school=source.get('university') or '大学待核对'
    material=source.get('material_type') or '课程学习资料'
    term=source.get('term') if source.get('term') not in {None,'','未标注'} else '学期待核对'
    brand=source['preview_brand']['name']
    title=f'{school} {course} {term} {material} PDF'[:200]
    snippets=[]
    for page in pages:
        lines=[re.sub(r'\s+',' ',v).strip() for v in page['text'].splitlines()]
        useful=[v for v in lines if 8<=len(v)<=150 and not re.fullmatch(r'[\W\d_]+',v)
            and not v.upper().startswith('THE UNIVERSITY OF ') and not any(w in v for w in ['代写','包过','保分','可提交成品','原题答案','直接答案'])]
        if useful:snippets.append(f"第 {page['page']} 页："+'；'.join(useful[:2])[:160])
    body=(f'{brand}｜{school} {course}\n{term}｜{material}\n'
        f"资料形式：电子 PDF，共 {source['page_count']} 页。\n\n"
        '选页内容（以实物样张为准）：\n'+('\n'.join(snippets[:5]) if snippets else '选页未提取到足够文字，请先查看真实图片并补充介绍。')+
        '\n\n选购前请核对课程代码、学期和所需资料范围。图片为这份 PDF 的真实水印样张；完整 PDF 不包含在展示图片中。'
        '\n\n用于独立学习与复习，非学校官方材料，不作成绩或考试范围保证。电子资料，无需纸质邮寄；交付方式由人工确认。')
    if 'assignment' in material.lower():body+='\n仅提供学习参考、思路讲解和结构说明，请根据学校 Academic Integrity 要求独立完成作业。'
    return {'title':title,'description':body[:1500]}
