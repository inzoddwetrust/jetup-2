# jetup/handlers/projects.py
"""
Project carousel and investment flow handlers.
Allows users to browse projects, view details, and select investment options.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from models.user import User
from models.project import Project
from models.option import Option
from core.message_manager import MessageManager
from core.user_decorator import with_user
from services.stats_service import StatsService
from core.di import get_service
from states.fsm_states import ProjectCarouselState

logger = logging.getLogger(__name__)

projects_router = Router(name="projects_router")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def get_project_by_id(session: Session, project_id: int, user_lang: str) -> Project | None:
    """
    Get project by ID with language fallback and status check.

    Args:
        session: Database session
        project_id: Project ID
        user_lang: User's preferred language

    Returns:
        Project instance or None if not found/inactive
    """
    # Try user's language first
    project = session.query(Project).filter(
        Project.projectID == project_id,
        Project.lang == user_lang
    ).first()

    # Check status
    if project:
        if project.status in ['active', 'child']:
            return project
        else:
            return None  # Project is disabled

    # Fallback to English
    project = session.query(Project).filter(
        Project.projectID == project_id,
        Project.lang == 'en'
    ).first()

    # Check status of English version
    if project and project.status in ['active', 'child']:
        return project

    return None


# ============================================================================
# CAROUSEL HANDLERS
# ============================================================================

@projects_router.callback_query(F.data == "/projects")
@with_user
async def start_carousel(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Start project carousel from the first project."""
    # Delete previous message if exists
    try:
        await callback_query.message.delete()
    except Exception:
        pass

    # Get sorted projects from StatsService
    stats_service = get_service(StatsService)
    sorted_projects = await stats_service.get_sorted_projects() if stats_service else []

    if not sorted_projects:
        await message_manager.send_template(
            user=user,
            template_key='/projects/notFound',
            update=callback_query
        )
        return

    # Get first project
    first_project_id = sorted_projects[0]
    project = await get_project_by_id(session, first_project_id, user.lang or 'en')

    if not project:
        await message_manager.send_template(
            user=user,
            template_key='/projects/details/notFound',
            update=callback_query
        )
        return

    # Save current project to state
    await state.update_data(current_project_id=first_project_id)
    await state.set_state(ProjectCarouselState.current_project_index)

    # Send project card
    await message_manager.send_template(
        user=user,
        template_key='/projects',
        variables={
            'projectName': project.projectName,
            'projectTitle': project.projectTitle,
            'projectID': project.projectID
        },
        update=callback_query,
        override_media_id=project.linkImage
    )


@projects_router.callback_query(
    F.data.startswith("move_"),
    ProjectCarouselState.current_project_index
)
@with_user
async def move_project(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Navigate through projects (forward/backward)."""
    step = int(callback_query.data.split("_")[1])
    user_data = await state.get_data()
    current_project_id = user_data.get('current_project_id', 0)

    # Get sorted projects
    stats_service = get_service(StatsService)
    sorted_projects = await stats_service.get_sorted_projects() if stats_service else []

    if not sorted_projects:
        await callback_query.answer("No projects available")
        return

    try:
        # Calculate new index (circular navigation)
        current_index = sorted_projects.index(current_project_id)
        new_index = (current_index + step) % len(sorted_projects)
        new_project_id = sorted_projects[new_index]
    except ValueError:
        await callback_query.answer("Error: Project not found")
        logger.error(f"Project {current_project_id} not in sorted list")
        return

    # Get new project
    project = await get_project_by_id(session, new_project_id, user.lang or 'en')

    if not project:
        await callback_query.answer("Error: Project not found")
        return

    # Update state
    await state.update_data(current_project_id=new_project_id)

    # Update message
    try:
        await message_manager.send_template(
            user=user,
            template_key='/projects',
            variables={
                'projectName': project.projectName,
                'projectTitle': project.projectTitle,
                'projectID': project.projectID
            },
            update=callback_query,
            edit=True,
            override_media_id=project.linkImage
        )
    except Exception as e:
        logger.error(f"Error updating carousel: {e}")
        await callback_query.answer("Error updating message")


@projects_router.callback_query(
    F.data == "details",
    ProjectCarouselState.current_project_index
)
@with_user
async def view_project_details(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Show detailed project information."""
    user_data = await state.get_data()
    current_project_id = user_data.get('current_project_id')

    project = await get_project_by_id(session, current_project_id, user.lang or 'en')

    if not project:
        await message_manager.send_template(
            user=user,
            template_key='/projects/notFound',
            update=callback_query
        )
        return

    try:
        # Determine media type and ID
        media_id = project.linkVideo if project.linkVideo else project.linkImage
        media_type = 'video' if project.linkVideo else None

        await message_manager.send_template(
            user=user,
            template_key='/projects/details',
            variables={
                'projectName': project.projectName,
                'projectDescription': project.fullText,
                'projectID': project.projectID,
                'currentPosition': current_project_id
            },
            update=callback_query,
            edit=True,
            delete_original=bool(project.linkVideo),
            override_media_id=media_id,
            media_type=media_type
        )
    except Exception as e:
        logger.error(f"Error showing project details: {e}")
        await callback_query.answer("Error showing project details")


@projects_router.callback_query(F.data.startswith("back_from_details_"))
@with_user
async def back_to_specific_project(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Return to specific project from details view."""
    project_id = int(callback_query.data.split("_")[-1])

    # Update state
    await state.update_data(current_project_id=project_id)
    await state.set_state(ProjectCarouselState.current_project_index)

    # Get project
    project = await get_project_by_id(session, project_id, user.lang or 'en')

    if not project:
        await callback_query.answer("Project not found")
        return

    # Show project card
    try:
        await message_manager.send_template(
            user=user,
            template_key='/projects',
            variables={
                'projectName': project.projectName,
                'projectTitle': project.projectTitle,
                'projectID': project.projectID
            },
            update=callback_query,
            edit=True,
            override_media_id=project.linkImage
        )
    except Exception as e:
        logger.error(f"Error returning to project: {e}")
        await callback_query.answer("Error loading project")


# ============================================================================
# INVESTMENT FLOW
# ============================================================================

@projects_router.callback_query(
    F.data.startswith("invest_"),
    ProjectCarouselState.current_project_index
)
@with_user
async def invest_in_project(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Show investment options for selected project."""
    project_id = int(callback_query.data.split("_")[1])

    # Get project
    project = session.query(Project).filter_by(projectID=project_id).first()
    if not project:
        await callback_query.answer("Project not found...", show_alert=True)
        return

    # Check if this is a child project
    if project.status == "child":
        await message_manager.send_template(
            user=user,
            template_key='projects/invest/child_project',
            variables={
                'projectName': project.projectName,
                'projectID': project.projectID
            },
            update=callback_query,
            edit=True,
            override_media_id=project.linkImage
        )
        return

    # Get active options
    options = session.query(Option).filter_by(
        projectID=project_id,
        isActive=True
    ).all()

    if not options:
        await message_manager.send_template(
            user=user,
            template_key='/projects/invest/noOptions',
            variables={
                'projectName': project.projectName,
                'projectID': project.projectID
            },
            update=callback_query
        )
        await callback_query.answer("No options available", show_alert=True)
        return

    # Build template with options
    template_keys = ['/projects/invest']
    template_keys.extend(['/projects/invest/buttons'] * len(options))
    template_keys.append('/projects/invest/buttonBack')

    context = {
        'projectName': project.projectName,
        'projectID': project.projectID,
        'rgroup': {
            'packQty': [opt.packQty for opt in options],
            'packPrice': [opt.packPrice for opt in options]
        },
        'optionID': [opt.optionID for opt in options],
        'packQty': [opt.packQty for opt in options],
        'packPrice': [opt.packPrice for opt in options]
    }

    try:
        await message_manager.send_template(
            user=user,
            template_key=template_keys,
            variables=context,
            update=callback_query,
            edit=True,
            override_media_id=project.linkImage
        )
    except Exception as e:
        logger.error(f"Error showing investment options: {e}")
        await callback_query.answer("Error showing options")