"""LLM Prompt 模板集合"""

SEARCH_KEYWORDS_TEMPLATE = """
你是一个电商运营专家。请根据以下产品信息，生成 {count} 个用户可能在闲鱼/淘宝上搜索该产品时会使用的关键词。

产品名称：{product_name}
官方价格：{official_price}元

要求：
- 每个关键词 2-8 个字
- 贴近真实用户搜索习惯
- 不要使用官方品牌词（如果有）
- 每个关键词用逗号分隔

只返回关键词列表，不要多余的解释。
"""

PRICE_JUDGE_TEMPLATE = """
你是一个价格合规分析师。请判断以下商品是否属于乱价（低于官方授权价）。

产品名称：{product_name}
官方价格：{official_price}元
商品标题：{title}
商品价格：{price}元
卖家描述：{description}

判断标准：
- 价格低于官方价 → 乱价
- 价格明显过低（低于官方价50%以上）→ 可能是引流帖/赠品，标注为"疑似引流"
- 价格等于或高于官方价 → 正常

请返回 JSON：
{{"judgment": "violation"|"suspicious"|"normal", "reason": "判断理由"}}
"""

VISION_PRICE_TEMPLATE = """
图片中是电商平台的商品卡片，请识别图中的价格信息。

要求：
- 只提取数字价格
- 如果有多个价格，取实际售价（不是原价/划线价）
- 如果无法识别到价格，返回 null

请只返回纯数字或 null。
"""


class PromptTemplates:
    """Prompt 模板访问入口，方便 IDE 自动补全"""

    SEARCH_KEYWORDS = SEARCH_KEYWORDS_TEMPLATE
    PRICE_JUDGE = PRICE_JUDGE_TEMPLATE
    VISION_PRICE = VISION_PRICE_TEMPLATE
