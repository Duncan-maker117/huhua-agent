"""人工维护的 MCP 模板选型元数据；新增模板时必须显式补齐，不解析 HTML 猜测。"""

TEMPLATE_METADATA = {
    't001-jianyue': {'layout': '单栏', 'has_photo': True, 'style_tags': ['极简', '标准'], 'recommended_for': ['通用', '技术岗信息密度高']},
    't002-jianyue': {'layout': '单栏', 'has_photo': True, 'style_tags': ['商务', '深蓝横幅'], 'recommended_for': ['通用', '产品与运营']},
    't003-shenlan': {'layout': '单栏', 'has_photo': True, 'style_tags': ['清爽', '细线分区'], 'recommended_for': ['通用', '技术岗信息密度高']},
    't004-jianyue': {'layout': '单栏', 'has_photo': True, 'style_tags': ['灰条', '顶底装饰'], 'recommended_for': ['通用']},
    't1000': {'layout': '单栏', 'has_photo': True, 'style_tags': ['浅蓝', '色块标题'], 'recommended_for': ['通用']},
    't1001': {'layout': '单栏', 'has_photo': True, 'style_tags': ['浅蓝', '色块'], 'recommended_for': ['通用']},
    't1002-jianyue': {'layout': '单栏', 'has_photo': True, 'style_tags': ['淡青', '几何装饰'], 'recommended_for': ['通用']},
}
