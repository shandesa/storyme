import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { StoryAPI } from "../api/api";

export default function StoriesPage() {
  const [stories, setStories] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    const loadStories = async () => {
      const res = await StoryAPI.getStories();
      if (!res.error) setStories(res);
    };
    loadStories();
  }, []);

  return (
    <div>
      <h2>Select a Story</h2>
      {stories.map((story, index) => (
        <div key={index} onClick={() => navigate("/upload")}>
          {story.title || "Story"}
        </div>
      ))}
    </div>
  );
}
