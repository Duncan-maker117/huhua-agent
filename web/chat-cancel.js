(function (root) {
  async function cancelTurn(turn, fetcher = fetch) {
    if (turn.cancelPromise) return turn.cancelPromise;
    turn.cancelPromise = (async () => {
      // Wait until the chat endpoint has registered this exact turn. An early
      // click must not overtake the POST and accidentally cancel nothing.
      if (!await turn.accepted) return false;
      const response = await fetcher(`/api/chat/session/${encodeURIComponent(turn.session)}/cancel?turn_id=${encodeURIComponent(turn.id)}`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('中断未成功，请重试');
      const result = await response.json();
      if (result.cancelled) {
        turn.cancelled = true;
        turn.controller.abort();
      }
      return Boolean(result.cancelled);
    })();
    try { return await turn.cancelPromise; }
    catch (error) { turn.cancelPromise = null; throw error; }
  }
  const api = {cancelTurn};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HuhuaChatCancel = api;
})(typeof window !== 'undefined' ? window : globalThis);
