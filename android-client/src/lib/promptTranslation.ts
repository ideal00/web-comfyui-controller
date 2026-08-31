export interface ParsedPromptTranslation {
  positive: string
  negative: string
}

function stripCodeFence(value: string): string {
  return value.replace(/```(?:text|markdown|md)?/gi, '').replace(/```/g, '').trim()
}

/** Parse the stable two-line format requested by the shared AI instruction. */
export function parsePromptTranslation(value: string): ParsedPromptTranslation {
  const raw = stripCodeFence(value)
  if (!raw) return { positive: '', negative: '' }
  const positiveMatch = raw.match(/(?:^|\n)\s*(?:POSITIVE|正向(?:提示词)?)\s*[:：]\s*([\s\S]*?)(?=\n\s*(?:NEGATIVE|负面(?:提示词)?)\s*[:：]|$)/i)
  const negativeMatch = raw.match(/(?:^|\n)\s*(?:NEGATIVE|负面(?:提示词)?)\s*[:：]\s*([\s\S]*)$/i)
  return {
    positive: (positiveMatch ? positiveMatch[1] : raw).trim(),
    negative: (negativeMatch ? negativeMatch[1] : '').trim(),
  }
}

/** Append an AI result without duplicating an existing exact prompt. */
export function appendPromptText(current: string, addition: string): string {
  const existing = current.trim()
  const incoming = addition.trim()
  if (!incoming) return existing
  if (!existing) return incoming
  if (existing.toLocaleLowerCase().includes(incoming.toLocaleLowerCase())) return existing
  return `${existing}, ${incoming}`
}
