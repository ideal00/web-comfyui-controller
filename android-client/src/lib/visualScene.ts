/** Build a structured Easy Panel visual scene from RPGBox state. */
import type { CharacterProfile, GameSession, StorySegment } from '../types'
import type { VisualCharacter, VisualScene } from '../services/easyPanelVisual'

function lastExpression(segments: StorySegment[], characterId: string): string {
  for (let index = segments.length - 1; index >= 0; index -= 1) {
    const segment = segments[index]
    if (segment.type === 'dialogue' && segment.characterId === characterId && segment.expression) return segment.expression
  }
  return ''
}

function characterVisual(character: CharacterProfile, segments: StorySegment[]): VisualCharacter {
  return {
    id: character.id,
    name: character.name,
    gender: character.gender,
    expression: lastExpression(segments, character.id),
  }
}

function recentNarration(segments: StorySegment[]): string {
  return segments
    .filter((segment) => segment.type === 'narration')
    .slice(-2)
    .map((segment) => segment.text.trim())
    .filter(Boolean)
    .join(' ')
    .slice(0, 700)
}

export function buildVisualScene(game: GameSession, segments: StorySegment[]): VisualScene {
  const presentIds = new Set([
    ...(game.gameState.presentCharacterIds ?? []),
    ...game.characters.filter((character) => character.role === 'player').map((character) => character.id),
  ])
  const characters = game.characters
    .filter((character) => presentIds.has(character.id))
    .map((character) => characterVisual(character, segments))

  return {
    characters,
    location: game.gameState.location,
    time: game.gameState.time,
    scene: recentNarration(segments),
  }
}

export function visualSceneSignature(game: GameSession, segments: StorySegment[]): string {
  const scene = buildVisualScene(game, segments)
  return JSON.stringify({
    location: scene.location ?? '',
    time: scene.time ?? '',
    characters: scene.characters.map((character) => [character.id, character.expression ?? '']),
  })
}
