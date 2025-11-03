# jetup/handlers/projects.py
"""
Project carousel and investment flow handlers.
Allows users to browse projects, view details, and select investment options.
"""
import logging
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram import Router, F, Bot
from sqlalchemy.orm import Session
from decimal import Decimal

from models.user import User
from models.project import Project
from models.option import Option
from core.message_manager import MessageManager
from core.user_decorator import with_user
from config import Config
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
    logger.info(f"User {user.userID} opened projects carousel")

    # Delete previous message if exists
    try:
        await callback_query.message.delete()
    except Exception:
        pass

    # Get sorted projects from Config dynamic values
    sorted_projects = await Config.get_dynamic(Config.SORTED_PROJECTS)

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

    # Get sorted projects from Config dynamic values
    sorted_projects = await Config.get_dynamic(Config.SORTED_PROJECTS)

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


# ============================================================================
# OPTION SELECTION & PURCHASE
# ============================================================================

@projects_router.callback_query(F.data.startswith("buy_option_"))
@with_user
async def handle_option_selection(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Handle option selection - show purchase confirmation.
    Check if user has sufficient balance.
    """
    option_id = int(callback_query.data.split("_")[2])

    logger.info(f"User {user.telegramID} selected option {option_id}")

    # Get option
    option = session.query(Option).filter_by(optionID=option_id).first()

    if not option:
        await callback_query.answer("Option not found!", show_alert=True)
        return

    # Get project
    project = await get_project_by_id(session, option.projectID, user.lang or 'en')

    if not project:
        await callback_query.answer("Project not found!", show_alert=True)
        return

    # Check balance
    if user.balanceActive >= option.packPrice:
        # Sufficient balance - show confirmation screen
        await message_manager.send_template(
            user=user,
            template_key='/projects/invest/purchaseStart',
            variables={
                'projectName': project.projectName,
                'projectID': project.projectID,
                'packQty': int(option.packQty),
                'packPrice': float(option.packPrice),
                'optionID': option.optionID
            },
            update=callback_query,
            edit=True,
            override_media_id=project.linkImage
        )
    else:
        # Insufficient balance
        await message_manager.send_template(
            user=user,
            template_key='/projects/invest/insufficientFunds',
            variables={
                'balance': float(user.balanceActive),
                'price': float(option.packPrice),
                'projectID': option.projectID
            },
            update=callback_query,
            edit=True,
            override_media_id=project.linkImage
        )


@projects_router.callback_query(F.data.startswith("confirm_purchase_"))
@with_user
async def confirm_purchase(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        bot: Bot
):
    """
    Confirm and execute purchase.

    Process:
    1. Lock user and option (pessimistic locking)
    2. Check balance again
    3. Create Purchase
    4. Deduct from ActiveBalance (table + field)
    5. Emit MLM event for commission processing
    6. Show success message
    """
    option_id = int(callback_query.data.split("_")[2])

    logger.info(f"User {user.telegramID} confirming purchase of option {option_id}")

    try:
        # Lock user for update (prevent race conditions)
        user = session.query(User).filter_by(
            userID=user.userID
        ).with_for_update().first()

        # Get option
        option = session.query(Option).filter_by(
            optionID=option_id
        ).first()

        if not user or not option:
            await callback_query.answer("Error processing purchase", show_alert=True)
            return

        # Check balance again (user might have spent money meanwhile)
        if user.balanceActive < option.packPrice:
            project = await get_project_by_id(session, option.projectID, user.lang or 'en')

            await message_manager.send_template(
                user=user,
                template_key='/projects/invest/insufficientFunds',
                variables={
                    'balance': float(user.balanceActive),
                    'price': float(option.packPrice),
                    'projectID': option.projectID
                },
                update=callback_query,
                edit=True,
                override_media_id=project.linkImage if project else None
            )
            return

        # Get project for display
        project = await get_project_by_id(session, option.projectID, user.lang or 'en')

        # Create Purchase
        from models.purchase import Purchase
        purchase = Purchase()
        purchase.userID = user.userID
        purchase.projectID = option.projectID
        purchase.projectName = option.projectName
        purchase.optionID = option.optionID
        purchase.packQty = option.packQty
        purchase.packPrice = option.packPrice

        # AuditMixin fields
        purchase.ownerTelegramID = user.telegramID
        purchase.ownerEmail = user.email

        session.add(purchase)
        session.flush()  # Get purchase.purchaseID

        logger.info(f"Created purchase {purchase.purchaseID} for user {user.userID}")

        # Convert price to Decimal
        pack_price = Decimal(str(option.packPrice))

        # Deduct from active balance (field)
        user.balanceActive -= pack_price

        # Create ActiveBalance transaction record
        from models.active_balance import ActiveBalance
        active_record = ActiveBalance()
        active_record.userID = user.userID
        active_record.firstname = user.firstname
        active_record.surname = user.surname
        active_record.amount = -pack_price  # Negative for deduction
        active_record.status = 'done'
        active_record.reason = f'purchase={purchase.purchaseID}'
        active_record.link = ''
        active_record.notes = 'Purchase payment'

        session.add(active_record)

        # Commit purchase and balance changes
        session.commit()

        logger.info(
            f"Purchase {purchase.purchaseID} completed: "
            f"user={user.userID}, amount={option.packPrice}"
        )

        # Emit MLM event for commission processing
        from mlm_system.events.event_bus import eventBus, MLMEvents

        await eventBus.emit(MLMEvents.PURCHASE_COMPLETED, {
            "purchaseId": purchase.purchaseID
        })

        logger.info(f"Emitted PURCHASE_COMPLETED event for purchase {purchase.purchaseID}")

        # Show success message
        try:
            await message_manager.send_template(
                user=user,
                template_key='/projects/invest/purchseSuccess',  # Note: typo in original
                variables={
                    'packQty': int(option.packQty),
                    'packPrice': float(option.packPrice),
                    'balance': float(user.balanceActive)
                },
                update=callback_query,
                edit=True,
                override_media_id=project.linkImage if project else None
            )
        except Exception as e:
            logger.error(f"Error showing success message: {e}")
            await callback_query.answer("Purchase completed!", show_alert=True)

    except Exception as e:
        session.rollback()
        logger.error(f"Error processing purchase: {e}", exc_info=True)
        await callback_query.answer("Error processing purchase", show_alert=True)


@projects_router.callback_query(
    F.data.regexp(r"^download_pdf_\d+~\w+$"),
    ProjectCarouselState.current_project_index
)
@with_user
async def download_project_pdf(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        bot: Bot
):
    """
    Download project presentation/documents.

    Format: download_pdf_{projectID}~{doc_id}
    Example: download_pdf_1~pres
    """
    logger.info(f"Processing PDF download: {callback_query.data}")

    try:
        # Parse callback data
        callback_parts = callback_query.data.split("_")
        if len(callback_parts) < 3:
            logger.warning(f"Invalid callback format: {callback_query.data}")
            await callback_query.answer("Invalid request format!")
            return

        # Extract projectID and doc_id
        project_doc = "_".join(callback_parts[2:])
        logger.debug(f"Extracted project_doc: {project_doc}")

        if "~" in project_doc:
            project_id_str, doc_id = project_doc.split("~", 1)
            project_id = int(project_id_str)
            logger.debug(f"Parsed project_id: {project_id}, doc_id: {doc_id}")
        else:
            project_id = int(project_doc)
            doc_id = None
            logger.debug(f"Parsed project_id: {project_id}, no doc_id")

        # Get project
        project = await get_project_by_id(session, project_id, user.lang or 'en')

        if not project:
            logger.warning(f"Project {project_id} not found")
            await callback_query.answer("Project not found!")
            return

        if not project.linkPres:
            logger.warning(f"Project {project_id} has no linkPres data")
            await callback_query.answer("No documents available!")
            return

        logger.info(f"Raw linkPres data: {repr(project.linkPres)}")

        # Parse linkPres (format: "pres: file_id, contract: file_id" OR just "file_id")
        link_pres = {}
        try:
            if ": " not in project.linkPres:
                # Single file_id format
                link_pres["default"] = project.linkPres.strip()
                logger.debug(f"Single link format: {link_pres['default']}")
            else:
                # Multiple files format
                cleaned = project.linkPres.replace(",\n", ",").replace(", ", ",")
                pairs = [pair.strip() for pair in cleaned.split(",") if pair.strip()]
                logger.debug(f"Found {len(pairs)} pairs: {pairs}")

                for pair in pairs:
                    if ": " in pair:
                        key, value = pair.split(": ", 1)
                        link_pres[key.strip()] = value.strip()
                    else:
                        link_pres["default"] = pair.strip()

            logger.info(f"Parsed link_pres: {link_pres}")

            # Select file_id
            selected_key = None
            file_id = None

            if doc_id and doc_id in link_pres:
                selected_key = doc_id
                file_id = link_pres[doc_id]
            elif link_pres:
                selected_key = next(iter(link_pres))
                file_id = link_pres[selected_key]
            else:
                logger.error("No valid links found")
                await callback_query.answer("No documents found!")
                return

            logger.info(f"Selected key: '{selected_key}', file_id: '{file_id}'")

            # Validate file_id format
            if not file_id or len(file_id) < 10:
                logger.error(f"Invalid file_id: {file_id}")
                await callback_query.answer("Document format not supported!")
                return

            # Send document
            await callback_query.answer("Downloading PDF...")

            try:
                await bot.send_document(
                    chat_id=callback_query.message.chat.id,
                    document=file_id,
                    caption=f"📄 {project.projectName}" + (f" - {selected_key}" if selected_key != "default" else "")
                )
                logger.info(f"Successfully sent document {file_id}")
            except Exception as send_error:
                logger.error(f"Failed to send document: {send_error}")
                await callback_query.message.answer(
                    f"❌ Failed to send document.\n"
                    f"File ID may be invalid or expired.\n"
                    f"Please contact support."
                )

        except ValueError as parse_error:
            logger.error(f"Failed to parse linkPres: {parse_error}")
            await callback_query.answer("Error processing document data!")

    except Exception as e:
        logger.error(f"Unexpected error in download_project_pdf: {e}", exc_info=True)
        await callback_query.answer("An error occurred!")