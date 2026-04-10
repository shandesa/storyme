async def generate_preview_stateless(
    self,
    child_name: str,
    story_id: str,
    face_image_path: str,
) -> str:
    """
    Stateless preview generation (NO MongoDB interaction).
    Generates only page 1 preview and returns image path.
    """

    # Load story
    story = _load_story(story_id)
    page = story["pages"][0]
    prompt = _build_prompt(story, page)

    # Generate base image (DALL-E)
    template_path, meta = await dalle_service.generate_image(
        prompt=prompt,
        story_id=story_id,
        page_number=page["page_number"],
        size=story.get("image_size", "1024x1024"),
    )

    # Output path (unique)
    output_path = str(BLENDED_DIR / f"{uuid.uuid4().hex}_preview.png")

    # Face blend + text overlay
    _process_page(
        template_path=template_path,
        user_face_path=face_image_path,
        face_bbox=meta["face_bbox"],
        text_area=meta["text_area"],
        story_lines=page["story_lines"],
        child_name=child_name,
        output_path=output_path,
    )

    return output_path
