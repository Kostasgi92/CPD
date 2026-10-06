"""Web εφαρμογή: streamlit run app.py"""

from __future__ import annotations

import os

import streamlit as st

from astrovid.config import VOICES, Settings
from astrovid.pipeline import generate

st.set_page_config(page_title="AstroVid", page_icon="🔭", layout="centered")
st.title("🔭 AstroVid")
st.caption("Σύντομα ενημερωτικά βίντεο αστροφυσικής (2–5 λεπτά): το Claude απαντά στην ερώτησή σας "
           "και η απάντηση επαληθεύεται με peer-reviewed δημοσιεύσεις, ανασκοπήσεις, NASA/ESA/ESO "
           "και επιστημονικά περιοδικά (New Scientist, Scientific American, Quanta κ.ά.).")

if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
    st.warning("Δεν έχει οριστεί `ANTHROPIC_API_KEY`. Δείτε το README για τη ρύθμιση.")

c_lang, c_voice = st.columns(2)
language = c_lang.selectbox("Γλώσσα αφήγησης", ["el", "en"], format_func={"el": "Ελληνικά", "en": "English"}.get)
voice = c_voice.selectbox("Φωνή", list(VOICES[language]), format_func=VOICES[language].get)

with st.form("video"):
    topic = st.text_input("Θέμα", placeholder="π.χ. Η ένταση του Hubble")
    description = st.text_area(
        "Περιγραφή",
        placeholder="π.χ. Γιατί οι μετρήσεις του ρυθμού διαστολής του Σύμπαντος διαφωνούν; "
                    "Τι λένε τα νέα δεδομένα του JWST και του DESI;",
        height=120,
    )
    c1, c2 = st.columns(2)
    minutes = c1.slider("Διάρκεια (λεπτά)", 2.0, 5.0, 3.0, 0.5)
    aspect = c2.selectbox("Μορφή", ["16:9", "9:16", "16:9-720p"],
                          format_func={"16:9": "Οριζόντιο 1080p", "9:16": "Κάθετο (Shorts/Reels)",
                                       "16:9-720p": "Οριζόντιο 720p (γρηγορότερο)"}.get)
    web = st.checkbox("Επαλήθευση με τα πιο πρόσφατα δεδομένα από NASA/ESA/ESO και ιστότοπους περιοδικών",
                      value=True)
    submitted = st.form_submit_button("🎬 Δημιουργία βίντεο", type="primary")

if submitted:
    if not topic.strip():
        st.error("Γράψτε ένα θέμα.")
        st.stop()
    settings = Settings()
    settings.use_web_search = web
    bar = st.progress(0.0, text="Ξεκινάμε…")
    log = st.status("Εργασία σε εξέλιξη…", expanded=True)

    def progress(msg: str, frac: float | None = None) -> None:
        if frac is not None:
            bar.progress(min(max(frac, 0.0), 1.0), text=msg)
        log.write(msg)

    try:
        result = generate(topic.strip(), description.strip() or topic.strip(), minutes=minutes,
                          language=language, voice=voice, aspect=aspect, settings=settings,
                          progress=progress)
    except Exception as exc:  # εμφάνιση του σφάλματος στο UI
        log.update(label="Σφάλμα", state="error")
        st.exception(exc)
        st.stop()
    log.update(label="Ολοκληρώθηκε", state="complete", expanded=False)
    st.session_state["result"] = result

result = st.session_state.get("result")
if result:
    st.subheader(result.script.title)
    st.caption(result.script.subtitle)
    st.video(str(result.video))
    for w in result.warnings:
        st.warning(w)
    st.download_button("⬇️ Λήψη MP4", result.video.read_bytes(), file_name=result.video.name,
                       mime="video/mp4")

    tab_answer, tab_script, tab_sources, tab_check, tab_brief = st.tabs(
        ["Απάντηση Claude", "Σενάριο", "Πηγές", "Επιστημονικός έλεγχος", "Έρευνα"])
    with tab_answer:
        st.caption("Η απάντηση του Claude στην ερώτησή σας, πάνω στην οποία χτίστηκε το βίντεο. "
                   "Η επαλήθευσή της με τις πηγές είναι στην καρτέλα «Έρευνα».")
        st.markdown(result.answer)
    by_id = {s.id: s for s in result.sources}
    with tab_script:
        for i, scene in enumerate(result.script.scenes, 1):
            st.markdown(f"**{i}. {scene.heading}**")
            st.write(scene.narration)
            refs = [by_id[s].short_ref() for s in scene.source_ids if s in by_id]
            st.caption("Πηγές: " + ("; ".join(refs) if refs else "—"))
    with tab_sources:
        labels = {"peer-reviewed": "📗 Peer-reviewed", "review": "📘 Ανασκόπηση",
                  "preprint": "📙 Preprint", "web": "🌐 Οργανισμός/περιοδικό",
                  "magazine": "📰 Επιστημονική δημοσιογραφία"}
        for s in result.sources:
            link = f"https://doi.org/{s.doi}" if s.doi else s.url
            st.markdown(f"**[{s.id}]** {labels.get(s.kind, s.kind)} — [{s.title}]({link})  \n"
                        f"<small>{s.short_ref()}</small>", unsafe_allow_html=True)
    with tab_check:
        if result.corrections:
            for c in result.corrections:
                st.markdown(f"- {c}")
        else:
            st.write("Ο έλεγχος δεν βρήκε κάτι προς διόρθωση.")
    with tab_brief:
        st.markdown(result.brief)
    st.caption(f"Όλα τα αρχεία: `{result.folder}`")
