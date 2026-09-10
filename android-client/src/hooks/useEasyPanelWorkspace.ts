import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { EasyPanelVisualConfig } from '../services/easyPanelVisual'
import {
  checkEasyPanelDuplicate,
  cleanableTaskCount,
  controlEasyPanelTask,
  getEasyPanelTasks,
  safeTaskId,
  taskCountsSummary,
  type EasyPanelDuplicateCheck,
  type EasyPanelTaskAction,
  type EasyPanelTaskSnapshot,
} from '../services/easyPanelTasks'
import {
  addEasyPanelProjectItems,
  addEasyPanelProjectLink,
  createEasyPanelProject,
  deleteEasyPanelProject,
  getEasyPanelProject,
  getEasyPanelProjects,
  removeEasyPanelProjectItems,
  removeEasyPanelProjectLink,
  setEasyPanelProjectCover,
  updateEasyPanelProject,
  updateEasyPanelProjectItem,
  type EasyPanelProject,
  type EasyPanelProjectDetail,
} from '../services/easyPanelProjects'

const TASK_POLL_MS = 3000

export type EasyPanelDuplicateVerdict = 'proceed' | 'duplicate' | 'error'

export interface EasyPanelWorkspace {
  taskCenterOpen: boolean
  setTaskCenterOpen: (open: boolean) => void
  tasks: EasyPanelTaskSnapshot | null
  tasksLoading: boolean
  tasksMessage: string
  tasksError: string
  taskSummary: string
  cleanableCount: number
  refreshTasks: () => Promise<void>
  controlTask: (action: EasyPanelTaskAction, extra?: Record<string, unknown>) => Promise<boolean>
  toggleTaskSelected: (taskId: string, selected: boolean) => Promise<void>
  duplicate: EasyPanelDuplicateCheck | null
  duplicateTitle: string
  checkGenerate: (payload: Record<string, unknown>) => Promise<EasyPanelDuplicateVerdict>
  dismissDuplicate: () => void
  projectsOpen: boolean
  setProjectsOpen: (open: boolean) => void
  projects: EasyPanelProject[]
  projectDetail: EasyPanelProjectDetail | null
  projectsLoading: boolean
  projectMessage: string
  projectError: string
  refreshProjects: () => Promise<void>
  openProject: (projectId: string) => Promise<void>
  createProject: (name: string, sectionsText?: string) => Promise<boolean>
  renameProject: (name: string) => Promise<boolean>
  updateProjectSections: (sectionsText: string) => Promise<boolean>
  deleteProject: () => Promise<boolean>
  addGenerationToProject: (projectId: string, generationId: string, section?: string) => Promise<boolean>
  moveProjectItem: (itemId: string, section: string) => Promise<boolean>
  removeProjectItem: (itemId: string) => Promise<boolean>
  setProjectCover: (generationId: string) => Promise<boolean>
  addProjectLink: (kind: string, ref: string, label?: string) => Promise<boolean>
  removeProjectLink: (linkId: string) => Promise<boolean>
  pickerOpen: boolean
  pickerGenerationId: string
  openProjectPicker: (generationId: string) => void
  closeProjectPicker: () => void
}

export function useEasyPanelWorkspace(config: EasyPanelVisualConfig): EasyPanelWorkspace {
  const [taskCenterOpen, setTaskCenterOpen] = useState(false)
  const [tasks, setTasks] = useState<EasyPanelTaskSnapshot | null>(null)
  const [tasksLoading, setTasksLoading] = useState(false)
  const [tasksMessage, setTasksMessage] = useState('打开后读取电脑端任务队列')
  const [tasksError, setTasksError] = useState('')
  const [duplicate, setDuplicate] = useState<EasyPanelDuplicateCheck | null>(null)
  const [duplicateTitle, setDuplicateTitle] = useState('')
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [projects, setProjects] = useState<EasyPanelProject[]>([])
  const [projectDetail, setProjectDetail] = useState<EasyPanelProjectDetail | null>(null)
  const [projectsLoading, setProjectsLoading] = useState(false)
  const [projectMessage, setProjectMessage] = useState('')
  const [projectError, setProjectError] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerGenerationId, setPickerGenerationId] = useState('')
  const requestRef = useRef(0)
  const duplicateCheckRef = useRef(false)

  const refreshTasks = useCallback(async () => {
    if (!config.token.trim()) {
      setTasksError('请先填写 RPG Token，再查看任务队列。')
      return
    }
    const requestNumber = requestRef.current + 1
    requestRef.current = requestNumber
    setTasksLoading(true)
    try {
      const snapshot = await getEasyPanelTasks(config)
      if (requestRef.current !== requestNumber) return
      setTasks(snapshot)
      setTasksError('')
      setTasksMessage(snapshot.message || '任务队列已同步。')
    } catch (caught) {
      if (requestRef.current !== requestNumber) return
      setTasksError(caught instanceof Error ? caught.message : '读取任务队列失败。')
    } finally {
      if (requestRef.current === requestNumber) setTasksLoading(false)
    }
  }, [config])

  const controlTask = useCallback(async (action: EasyPanelTaskAction, extra: Record<string, unknown> = {}) => {
    if (!config.token.trim()) {
      setTasksError('请先填写 RPG Token。')
      return false
    }
    setTasksLoading(true)
    try {
      const snapshot = await controlEasyPanelTask(config, action, extra)
      setTasks(snapshot)
      setTasksError('')
      setTasksMessage(snapshot.message || '队列已更新。')
      return true
    } catch (caught) {
      setTasksError(caught instanceof Error ? caught.message : '队列操作失败。')
      return false
    } finally {
      setTasksLoading(false)
    }
  }, [config])

  const toggleTaskSelected = useCallback(async (taskId: string, selected: boolean) => {
    const wanted = safeTaskId(taskId)
    if (!wanted) {
      setTasksError('任务编号无效。')
      return
    }
    await controlTask('select', { ids: [wanted], selected })
  }, [controlTask])

  const checkGenerate = useCallback(async (payload: Record<string, unknown>): Promise<EasyPanelDuplicateVerdict> => {
    if (duplicateCheckRef.current) return 'proceed'
    duplicateCheckRef.current = true
    try {
      const result = await checkEasyPanelDuplicate(config, payload)
      if (result.duplicate && result.duplicates.length) {
        setDuplicate(result)
        setDuplicateTitle('发现完全相同的生成任务')
        return 'duplicate'
      }
      return 'proceed'
    } catch {
      // 检测失败不阻塞生成：宁可多出一张，也不要让用户卡住。
      return 'proceed'
    } finally {
      duplicateCheckRef.current = false
    }
  }, [config])

  const dismissDuplicate = useCallback(() => setDuplicate(null), [])

  const refreshProjects = useCallback(async () => {
    if (!config.token.trim()) {
      setProjectError('请先填写 RPG Token，再查看作品项目。')
      return
    }
    setProjectsLoading(true)
    try {
      const listed = await getEasyPanelProjects(config)
      setProjects(listed.items)
      setProjectError('')
      setProjectMessage(listed.items.length ? `共 ${listed.total} 个项目。` : '还没有项目，可以新建一个角色图集。')
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '读取项目失败。')
    } finally {
      setProjectsLoading(false)
    }
  }, [config])

  const openProject = useCallback(async (projectId: string) => {
    setProjectsLoading(true)
    try {
      const detail = await getEasyPanelProject(config, projectId)
      setProjectDetail(detail)
      setProjectError('')
      setProjectMessage(`「${detail.project.name}」共 ${detail.total} 件作品。`)
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '读取项目详情失败。')
    } finally {
      setProjectsLoading(false)
    }
  }, [config])

  const reloadDetail = useCallback(async () => {
    if (projectDetail?.project.project_id) await openProject(projectDetail.project.project_id)
    await refreshProjects()
  }, [openProject, projectDetail?.project.project_id, refreshProjects])

  const createProject = useCallback(async (name: string, sectionsText?: string) => {
    try {
      await createEasyPanelProject(config, name, sectionsText === undefined ? {} : { sections: sectionsText })
      setProjectError('')
      await refreshProjects()
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '新建项目失败。')
      return false
    }
  }, [config, refreshProjects])

  const renameProject = useCallback(async (name: string) => {
    if (!projectDetail) return false
    try {
      await updateEasyPanelProject(config, projectDetail.project.project_id, { name })
      setProjectError('')
      await reloadDetail()
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '项目改名失败。')
      return false
    }
  }, [config, projectDetail, reloadDetail])

  const updateProjectSections = useCallback(async (sectionsText: string) => {
    if (!projectDetail) return false
    try {
      await updateEasyPanelProject(config, projectDetail.project.project_id, { sections: sectionsText })
      setProjectError('')
      await reloadDetail()
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '分区保存失败。')
      return false
    }
  }, [config, projectDetail, reloadDetail])

  const deleteProject = useCallback(async () => {
    if (!projectDetail) return false
    try {
      await deleteEasyPanelProject(config, projectDetail.project.project_id)
      setProjectDetail(null)
      setProjectError('')
      await refreshProjects()
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '删除项目失败。')
      return false
    }
  }, [config, projectDetail, refreshProjects])

  const addGenerationToProject = useCallback(async (projectId: string, generationId: string, section = '') => {
    try {
      const result = await addEasyPanelProjectItems(config, projectId, [generationId], section)
      setProjectError('')
      setProjectMessage(`已加入项目（新增 ${Number(result.added ?? 0)} 件）。`)
      await refreshProjects()
      if (projectDetail?.project.project_id === projectId) await openProject(projectId)
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '加入项目失败。')
      return false
    }
  }, [config, openProject, projectDetail?.project.project_id, refreshProjects])

  const moveProjectItem = useCallback(async (itemId: string, section: string) => {
    if (!projectDetail) return false
    try {
      await updateEasyPanelProjectItem(config, projectDetail.project.project_id, itemId, { section })
      setProjectError('')
      await openProject(projectDetail.project.project_id)
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '分区调整失败。')
      return false
    }
  }, [config, openProject, projectDetail])

  const removeProjectItem = useCallback(async (itemId: string) => {
    if (!projectDetail) return false
    try {
      await removeEasyPanelProjectItems(config, projectDetail.project.project_id, { itemIds: [itemId] })
      setProjectError('')
      await reloadDetail()
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '移出项目失败。')
      return false
    }
  }, [config, projectDetail, reloadDetail])

  const setProjectCover = useCallback(async (generationId: string) => {
    if (!projectDetail) return false
    try {
      await setEasyPanelProjectCover(config, projectDetail.project.project_id, generationId)
      setProjectError('')
      await reloadDetail()
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '封面设置失败。')
      return false
    }
  }, [config, projectDetail, reloadDetail])

  const addProjectLink = useCallback(async (kind: string, ref: string, label = '') => {
    if (!projectDetail) return false
    try {
      await addEasyPanelProjectLink(config, projectDetail.project.project_id, kind, ref, label)
      setProjectError('')
      await openProject(projectDetail.project.project_id)
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '关联失败。')
      return false
    }
  }, [config, openProject, projectDetail])

  const removeProjectLink = useCallback(async (linkId: string) => {
    if (!projectDetail) return false
    try {
      await removeEasyPanelProjectLink(config, projectDetail.project.project_id, linkId)
      setProjectError('')
      await openProject(projectDetail.project.project_id)
      return true
    } catch (caught) {
      setProjectError(caught instanceof Error ? caught.message : '取消关联失败。')
      return false
    }
  }, [config, openProject, projectDetail])

  const openProjectPicker = useCallback((generationId: string) => {
    setPickerGenerationId(generationId)
    setPickerOpen(true)
    void refreshProjects()
  }, [refreshProjects])

  const closeProjectPicker = useCallback(() => {
    setPickerOpen(false)
    setPickerGenerationId('')
  }, [])

  // 只有打开任务中心时才轮询，避免后台常驻请求。
  useEffect(() => {
    if (!taskCenterOpen) return
    void refreshTasks()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refreshTasks()
    }, TASK_POLL_MS)
    return () => clearInterval(timer)
  }, [refreshTasks, taskCenterOpen])

  useEffect(() => {
    if (!projectsOpen) return
    void refreshProjects()
  }, [projectsOpen, refreshProjects])

  const taskSummary = useMemo(() => taskCountsSummary(tasks?.counts), [tasks?.counts])
  const cleanableCount = useMemo(() => cleanableTaskCount(tasks?.counts), [tasks?.counts])

  return {
    taskCenterOpen,
    setTaskCenterOpen,
    tasks,
    tasksLoading,
    tasksMessage,
    tasksError,
    taskSummary,
    cleanableCount,
    refreshTasks,
    controlTask,
    toggleTaskSelected,
    duplicate,
    duplicateTitle,
    checkGenerate,
    dismissDuplicate,
    projectsOpen,
    setProjectsOpen,
    projects,
    projectDetail,
    projectsLoading,
    projectMessage,
    projectError,
    refreshProjects,
    openProject,
    createProject,
    renameProject,
    updateProjectSections,
    deleteProject,
    addGenerationToProject,
    moveProjectItem,
    removeProjectItem,
    setProjectCover,
    addProjectLink,
    removeProjectLink,
    pickerOpen,
    pickerGenerationId,
    openProjectPicker,
    closeProjectPicker,
  }
}
