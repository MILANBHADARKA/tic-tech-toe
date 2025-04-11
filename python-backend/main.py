from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import pdfplumber
import re
from sentence_transformers import SentenceTransformer, util
import io
from typing import List
import pandas as pd
from sklearn.cluster import KMeans

app = FastAPI()

# Load model once
model = SentenceTransformer('all-MiniLM-L6-v2')

known_skills = list(set([
    "python", "numpy", "pandas", "matplotlib", "seaborn", "plotly", "cufflinks", "geoplotting",
    "machine learning", "deep learning", "cnn", "ann", "supervised learning", "unsupervised learning",
    "php", "django", "html", "css", "sql", "javascript", "c", "c++",
    "data structures", "algorithms", "xgboost", "k-means", "transformers", "llms",
    "hugging face", "t5", "wav2vec2", "google colab", "flask", "streamlit", "react",
    "pytorch", "tensorflow", "linux", "git", "docker", "mysql", "postgresql"
]))
skill_embeddings = model.encode(known_skills, convert_to_tensor=True)

career_mapping = {
    0: "Machine Learning Engineer",
    1: "Frontend Web Developer",
    2: "Backend Web Developer",
    3: "App Developer",
    4: "Cloud Engineer",
    5: "Generalist / Software Engineer"
}

def clean_resume_text(text):
    text = re.sub(r'[•|]', '\n', text)
    text = re.sub(r'\s+', ' ', text)
    return text.lower()

def extract_skills_from_resume(resume_text, similarity_threshold=0.3):
    resume_text = clean_resume_text(resume_text)
    phrases = re.split(r'[\n,.;:]', resume_text)
    phrases = [phrase.strip() for phrase in phrases if len(phrase.strip()) >= 2]
    phrase_embeddings = model.encode(phrases, convert_to_tensor=True)

    extracted_skills = set()
    for i, phrase in enumerate(phrases):
        sim = util.cos_sim(phrase_embeddings[i], skill_embeddings)
        top_idx = sim.argmax().item()
        top_score = sim[0][top_idx].item()
        if top_score >= similarity_threshold:
            extracted_skills.add(known_skills[top_idx])

    return sorted(extracted_skills)

def extract_text_from_pdf(file_bytes):
    full_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    return full_text.strip()

@app.post("/extract-skills")
async def extract_skills(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        return JSONResponse(status_code=400, content={"error": "Only PDF files are supported."})

    file_bytes = await file.read()
    resume_text = extract_text_from_pdf(file_bytes)
    skills = extract_skills_from_resume(resume_text)
    return {"extracted_skills": skills}

@app.post("/suggest-career")
async def suggest_career(files: List[UploadFile] = File(...)):
    all_skills_per_resume = []
    file_names = []

    for file in files:
        if file.content_type != "application/pdf":
            return JSONResponse(status_code=400, content={"error": f"{file.filename} is not a PDF."})

        file_bytes = await file.read()
        resume_text = extract_text_from_pdf(file_bytes)
        skills = extract_skills_from_resume(resume_text)
        all_skills_per_resume.append(skills)
        file_names.append(file.filename)

    # Create a flat skill list
    all_skills = list(set([skill.lower() for resume in all_skills_per_resume for skill in resume]))

    # Binary skill matrix
    def build_skill_matrix(resumes, all_skills):
        matrix = []
        for skills in resumes:
            row = [1 if skill in skills else 0 for skill in all_skills]
            matrix.append(row)
        return pd.DataFrame(matrix, columns=all_skills)

    skill_df = build_skill_matrix(all_skills_per_resume, all_skills)

    # Clustering
    k = min(6, len(files))  # ensure k <= number of files
    kmeans = KMeans(n_clusters=k, random_state=42)
    skill_df["cluster"] = kmeans.fit_predict(skill_df)

    # Determine top skills per cluster
    cluster_to_top_skills = {}
    for cluster_num in range(k):
        cluster_skills = skill_df[skill_df["cluster"] == cluster_num].drop(columns=["cluster"]).sum()
        top_skills = cluster_skills.sort_values(ascending=False).head(5).index.tolist()
        cluster_to_top_skills[cluster_num] = top_skills

    # Assign careers (you can improve this logic)
    cluster_to_career = {}
    for cluster_num, skills in cluster_to_top_skills.items():
        if "machine learning" in skills or "pytorch" in skills or "tensorflow" in skills:
            cluster_to_career[cluster_num] = "Machine Learning Engineer"
        elif "html" in skills or "css" in skills or "javascript" in skills:
            cluster_to_career[cluster_num] = "Frontend Web Developer"
        elif "django" in skills or "flask" in skills or "sql" in skills:
            cluster_to_career[cluster_num] = "Backend Web Developer"
        elif "flutter" in skills or "android" in skills:
            cluster_to_career[cluster_num] = "App Developer"
        elif "docker" in skills or "linux" in skills or "aws" in skills:
            cluster_to_career[cluster_num] = "Cloud Engineer"
        else:
            cluster_to_career[cluster_num] = "Generalist / Software Engineer"

    # Prepare response
    results = []
    for idx, skills in enumerate(all_skills_per_resume):
        cluster = skill_df.iloc[idx]["cluster"]
        results.append({
            "file": file_names[idx],
            "skills": skills,
            "cluster": int(cluster),
            "career_suggestion": cluster_to_career[int(cluster)]
        })

    return {"results": results}
