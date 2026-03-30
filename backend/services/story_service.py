from typing import Optional, List
from models.story import Story, Page, FacePlacement


class StoryRepository:
    """Manages all available stories. Designed for easy extension."""
    
    def __init__(self):
        self._stories = self._initialize_stories()
    
    def _initialize_stories(self) -> dict:
        """Initialize all available stories. Easy to add more."""
        stories = {}
        
        # Story 1: Forest of Smiles
        forest_story = Story(
            story_id="forest_of_smiles",
            title="{name} and the Forest of Smiles",
            age_group="3-6",
            pages=[
                Page(
                    page_number=1,
                    text="One sunny morning, {name} walked into a beautiful forest filled with soft light and gentle sounds.\n\nEverything felt magical… as if the forest was waiting just for {name}.",
                    face_placement=FacePlacement(x=220, y=180, width=160, height=160),
                    template_filename="page1.png"
                ),
                Page(
                    page_number=2,
                    text="A fluffy rabbit hopped closer and said,\n\"Hello {name}! Welcome to the Forest of Smiles.\"\n\n{name} blinked… the rabbit could talk!",
                    face_placement=FacePlacement(x=200, y=200, width=150, height=150),
                    template_filename="page2.png"
                ),
                Page(
                    page_number=3,
                    text="Above them, birds sang sweet songs.\n\"Sing with us, {name}!\" they chirped happily.\n\n{name} smiled and listened to the melody.",
                    face_placement=FacePlacement(x=230, y=220, width=140, height=140),
                    template_filename="page3.png"
                ),
                Page(
                    page_number=4,
                    text="A big gentle elephant came forward and said,\n\"Kindness makes the forest shine.\"\n\n{name} touched its trunk and felt happy.",
                    face_placement=FacePlacement(x=210, y=210, width=150, height=150),
                    template_filename="page4.png"
                ),
                Page(
                    page_number=5,
                    text="A slow turtle whispered,\n\"Take your time, {name}. Every moment is special.\"\n\n{name} walked slowly… and noticed tiny flowers.",
                    face_placement=FacePlacement(x=240, y=230, width=140, height=140),
                    template_filename="page5.png"
                ),
                Page(
                    page_number=6,
                    text="A monkey swung down laughing,\n\"Let's play, {name}!\"\n\n{name} giggled and clapped with joy.",
                    face_placement=FacePlacement(x=200, y=190, width=150, height=150),
                    template_filename="page6.png"
                ),
                Page(
                    page_number=7,
                    text="A deer stood quietly and said,\n\"Peace lives in your heart, {name}.\"\n\n{name} took a deep breath and smiled softly.",
                    face_placement=FacePlacement(x=220, y=210, width=150, height=150),
                    template_filename="page7.png"
                ),
                Page(
                    page_number=8,
                    text="As evening came, tiny fireflies glowed around {name}.\n\"You bring light wherever you go,\" they whispered.\n\n{name} felt warm and special.",
                    face_placement=FacePlacement(x=230, y=200, width=140, height=140),
                    template_filename="page8.png"
                ),
                Page(
                    page_number=9,
                    text="A big tree spoke gently,\n\"You are kind, brave, and wonderful, {name}.\"\n\n{name} hugged the tree with love.",
                    face_placement=FacePlacement(x=210, y=220, width=150, height=150),
                    template_filename="page9.png"
                ),
                Page(
                    page_number=10,
                    text="As {name} walked home, the forest whispered,\n\"Come back anytime.\"\n\nAnd {name} knew… the smiles would always stay in the heart.",
                    face_placement=FacePlacement(x=220, y=200, width=150, height=150),
                    template_filename="page10.png"
                )
            ]
        )
        
        stories[forest_story.story_id] = forest_story
        
        # Future: Add more stories here by age group
        # stories["ocean_adventure"] = Story(...)
        # stories["space_journey"] = Story(...)
        
        return stories
    
    def get_story(self, story_id: str) -> Optional[Story]:
        """Retrieve a story by ID."""
        return self._stories.get(story_id)
    
    def get_all_stories(self) -> List[Story]:
        """Get all available stories."""
        return list(self._stories.values())
    
    def get_stories_by_age_group(self, age_group: str) -> List[Story]:
        """Filter stories by age group. For future use."""
        return [s for s in self._stories.values() if s.age_group == age_group]


# Singleton instance
story_repository = StoryRepository()
