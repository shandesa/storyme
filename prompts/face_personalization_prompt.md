# Face Personalization Pipeline Prompt (Reusable)

When image is entered by user, from that image, identify the face alone. Extract the face image. Then study the image template to identify where is the image template coordinates, if you are taking them from configuration file, then first identify correct image template coordinates (circle white), then identify the size of the image template circle. Accordingly, check if the image template circle is sized appropriate to the dimensions of the body. Then identify metadata for image template, such that the direction of the face, angle of the neck with respect to rest of the body width of the neck, colour of the neck etc is known. Take these parameters and using these parameters, fit the cropped face image into these dimensions, angle, thickness and complexion of the neck so it blends with body. Next, in the overlay place, after putting the face inside the template, fill the white area of the template with neighbouring pixels so as to blend into the surrounding.

## Key Steps:
1. **Face Detection & Extraction**: Use OpenCV Haar Cascades to detect and crop the face from the uploaded photo
2. **Template Analysis**: Identify the white circle placeholder on the template - find center, radius, and surrounding context
3. **Template Metadata**: Determine face angle, neck direction, neck width, neck color from the character's body in the template
4. **Face Fitting**: Resize the extracted face to fit the circle, match the angle/orientation of the template character
5. **Compositing**: Place the face inside the circle with proper alpha blending
6. **Inpainting**: Fill remaining white areas of the placeholder circle with neighboring pixel colors to blend seamlessly
7. **Text Replacement**: Find baked-in "{name}" text on templates and replace with actual child's name in matching style

## Template-Specific Data (page1.png - 1536x1024):
- Face circle: center=(985, 382), radius=135, bounds=(850,247)-(1120,517)
- Text "{name}" location: First text line y=188-208, x=200-600
- Text color: RGB(134, 105, 54) - dark brown
- Neck/below circle color: RGB(244, 219, 170)
- Hair/above circle color: RGB(161, 114, 64)
- Body/shirt color: RGB(236, 205, 110) - yellow
- Character orientation: slightly looking down-left
