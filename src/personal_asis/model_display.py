"""Model attribution for display; generated text and model history stay plain."""


def model_emoji(model):
    name = (model or '').rsplit('/', 1)[-1].lower()
    if name.startswith('deepseek'):
        return '🐳'
    if name.startswith('mimo'):
        return '🍚'
    if name.startswith('gemma-'):
        return '🧊'
    if name.startswith('gemini-') and 'flash' in name:
        return '✨' if 'lite' in name else '💫'
    return ''


def display_reply(text, model):
    emoji = model_emoji(model)
    if not emoji or not text or text.startswith(emoji+'\n\n'):
        return text
    return emoji+'\n\n'+text


class ModelReply(str):
    """Plain response text with trusted, separately persisted attribution."""
    def __new__(cls, text, model=''):
        if not isinstance(text,str):
            raise TypeError('reply_text_required')
        result = super().__new__(cls, text)
        result.asis_router_model = model
        return result
