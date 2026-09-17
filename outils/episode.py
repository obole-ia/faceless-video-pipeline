#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
episode.py — chaine de production video d'Obole.

Entree  : un fichier JSON decrivant l'episode (voir outils/episode.md).
Sortie  : un mp4 vertical 1080x1920, H.264 + AAC, faststart, pret a publier.

Voix    : Kokoro-82M ONNX (local, Apache-2.0, voix francaise ff_siwis) ;
          repli edge-tts (fr-FR-DeniseNeural / fr-FR-HenriNeural) si demande.
Rendu   : Pillow pour les images, ffmpeg pour l'encodage, libass pour les
          sous-titres incrustes. Aucun GPU, aucun service payant.

Univers : fond noir, mono blanc, une piece comme signe, aucun visage,
          aucun emoji, compteur de solde qui bat une fois par seconde.
"""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RACINE = Path(__file__).resolve().parent.parent          # /home/ubuntu/influenceur-ia
CACHE_TTS = RACINE / "outils" / "cache" / "tts"
MODELES = RACINE / "outils" / "modeles" / "kokoro"

# ----------------------------------------------------------------------------
# Gabarit visuel
# ----------------------------------------------------------------------------
L, H = 1080, 1920
FPS = 30
SR = 24000                       # frequence de la voix

BLANC = (238, 238, 238)
GRIS = (122, 122, 122)
GRIS_F = (56, 56, 56)

POLICE_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
POLICE_R = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
POLICE_ASS = "DejaVu Sans Mono"

# sous-titres : gros, contrastes, 2 lignes max, dans la zone lisible
ST_TAILLE = 62
ST_COLS = 25                     # caracteres par ligne (mono 62px = 37,3 px/car)
ST_LIGNES = 2
ST_MARGE_BAS = 500               # distance du bas de l'ecran

MARGE = 72
Y_ENTETE = 104
Y_REGLE_H = 158
Y_VIS_0, Y_VIS_1 = 268, 1020     # zone du visuel
Y_SOLDE_COMPACT = 1046
Y_REGLE_B = 1156
Y_PIED = 1664                    # dans la zone sure : l'UI des plateformes
                                 # recouvre les ~190 px du bas

# Mention visible obligatoire (AI Act art. 50, loi 2023-451). Discrete mais
# toujours lisible, et jamais dans la zone rognee/recouverte par les apps.
PIED = "Voix de synth\u00e8se \u00b7 contenu g\u00e9n\u00e9r\u00e9 par IA"

CIBLE_MIN, CIBLE_MAX = 60.0, 90.0

_polices = {}


def police(chemin, taille):
    cle = (chemin, taille)
    if cle not in _polices:
        _polices[cle] = ImageFont.truetype(chemin, taille)
    return _polices[cle]


def att(couleur, f):
    """Atténue une couleur (fondu sur fond noir)."""
    return tuple(max(0, min(255, int(v * f))) for v in couleur)


def texte_espace(d, xy, s, fnt, fill, espace=0, ancre="lt"):
    """Dessine du texte avec un interlettrage, ancre lt / mt / rt."""
    largeurs = [d.textlength(c, font=fnt) for c in s]
    total = sum(largeurs) + espace * max(0, len(s) - 1)
    x, y = xy
    if ancre[0] == "m":
        x -= total / 2
    elif ancre[0] == "r":
        x -= total
    for c, w in zip(s, largeurs):
        d.text((x, y), c, font=fnt, fill=fill, anchor="l" + ancre[1])
        x += w + espace
    return total


def piece(d, cx, cy, r, couleur, ep=None):
    """Le sigle d'Obole : une piece. Deux cercles concentriques, rien d'autre."""
    ep = ep or max(2, int(r * 0.075))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=couleur, width=ep)
    r2 = r * 0.44
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=couleur,
              width=max(2, int(ep * 0.8)))


# ----------------------------------------------------------------------------
# Voix
# ----------------------------------------------------------------------------
class VoixKokoro:
    nom = "kokoro"

    def libelle(self):
        return "Kokoro-82M ONNX (%s)" % self.voix

    def __init__(self, voix="ff_siwis", vitesse=1.0):
        onnx = MODELES / "kokoro-v1.0.onnx"
        bins = MODELES / "voices-v1.0.bin"
        if not onnx.exists() or not bins.exists():
            raise RuntimeError(
                "modele Kokoro absent : %s et %s attendus "
                "(voir outils/episode.md)" % (onnx, bins))
        from kokoro_onnx import Kokoro
        self.k = Kokoro(str(onnx), str(bins))
        if voix not in self.k.get_voices():
            raise RuntimeError("voix Kokoro inconnue : %s" % voix)
        self.voix = voix
        self.vitesse = vitesse

    def dire(self, texte):
        s, sr = self.k.create(texte, voice=self.voix, speed=self.vitesse,
                              lang="fr-fr")
        s = np.asarray(s, dtype=np.float32)
        if sr != SR:
            s = _reechantillonne(s, sr, SR)
        return s


class VoixEdge:
    nom = "edge"

    def libelle(self):
        return "edge-tts (%s)" % self.voix

    def __init__(self, voix="fr-FR-DeniseNeural", vitesse=1.0):
        import edge_tts
        self._mod = edge_tts          # verifie la presence a la construction
        self.voix = voix
        self.vitesse = vitesse
        pct = int(round((vitesse - 1.0) * 100))
        self.rate = "%+d%%" % pct

    def dire(self, texte):
        import asyncio
        import edge_tts
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            async def go():
                c = edge_tts.Communicate(texte, self.voix, rate=self.rate)
                await c.save(tmp.name)
            asyncio.run(go())
            brut = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", tmp.name, "-f", "f32le",
                 "-ac", "1", "-ar", str(SR), "-"],
                check=True, stdout=subprocess.PIPE).stdout
            return np.frombuffer(brut, dtype=np.float32).copy()
        finally:
            os.unlink(tmp.name)


def _reechantillonne(s, sr_in, sr_out):
    n = int(round(len(s) * sr_out / sr_in))
    xi = np.linspace(0, len(s) - 1, n, dtype=np.float64)
    return np.interp(xi, np.arange(len(s)), s).astype(np.float32)


def fabrique_voix(nom, vitesse, voix_nom=None):
    if nom == "kokoro":
        return VoixKokoro(voix_nom or "ff_siwis", vitesse)
    if nom == "edge":
        return VoixEdge(voix_nom or "fr-FR-DeniseNeural", vitesse)
    # auto : Kokoro d'abord (local, sans reseau), repli edge-tts
    try:
        return VoixKokoro(voix_nom or "ff_siwis", vitesse)
    except Exception as e:
        print("  ! Kokoro indisponible (%s) -> repli edge-tts" % e)
        return VoixEdge("fr-FR-DeniseNeural", vitesse)


class Diseur:
    """Synthese avec cache disque, pour que les rendus successifs soient rapides."""

    def __init__(self, voix, cache=True):
        self.voix = voix
        self.cache = cache
        self.temps_synthese = 0.0
        self.secondes_synthetisees = 0.0
        self.touches = 0
        CACHE_TTS.mkdir(parents=True, exist_ok=True)

    def dire(self, texte):
        cle = hashlib.sha1(
            ("%s|%s|%s|%s" % (self.voix.nom, getattr(self.voix, "voix", ""),
                              getattr(self.voix, "vitesse", 1.0), texte)
             ).encode("utf-8")).hexdigest()[:20]
        f = CACHE_TTS / ("%s.npy" % cle)
        if self.cache and f.exists():
            self.touches += 1
            return np.load(f)
        t0 = time.time()
        s = self.voix.dire(texte)
        dt = time.time() - t0
        self.temps_synthese += dt
        self.secondes_synthetisees += len(s) / SR
        if self.cache:
            np.save(f, s)
        return s


# ----------------------------------------------------------------------------
# Decoupage du texte : phrases (pour la prosodie) puis cartons (pour l'ecran)
# ----------------------------------------------------------------------------
def phrases(texte):
    t = " ".join(texte.split())
    bouts = re.split(r"(?<=[.!?…])\s+", t)
    return [b.strip() for b in bouts if b.strip()]


def replie(mots, cols, lignes):
    """Replie une liste de mots en <= `lignes` lignes de <= `cols` caracteres.
    Renvoie None si ca ne tient pas.

    Sur deux lignes on cherche la coupe la plus equilibree : un glouton laisse
    un orphelin d'un seul mot sur la deuxieme ligne, ce qui est laid et lit mal.
    """
    plein = " ".join(mots)
    if len(plein) <= cols:
        return [plein]
    if lignes == 2:
        mieux = None
        for i in range(1, len(mots)):
            a, b = " ".join(mots[:i]), " ".join(mots[i:])
            if len(a) <= cols and len(b) <= cols:
                score = max(len(a), len(b))
                if mieux is None or score < mieux[0]:
                    mieux = (score, [a, b])
        if mieux:
            return mieux[1]
    out, cur = [], ""
    for m in mots:
        cand = (cur + " " + m).strip()
        if len(cand) <= cols:
            cur = cand
        else:
            if cur:
                out.append(cur)
            if len(m) > cols:
                return None
            cur = m
        if len(out) > lignes:
            return None
    if cur:
        out.append(cur)
    return out if len(out) <= lignes else None


# ponctuation qui, en typographie francaise, prend une espace insecable AVANT
# et ne doit donc jamais commencer une ligne de sous-titre
PONCT_COLLEE = {":", ";", "!", "?", "\u00bb", "\u2026", "%"}


def mots_de(phrase):
    """Decoupe en mots, en collant la ponctuation qui ne peut pas debuter
    une ligne (« un but : gagner » ne doit pas casser avant les deux-points)."""
    out = []
    for t in phrase.split():
        if t in PONCT_COLLEE and out:
            out[-1] += "\u00a0" + t
        elif t == "\u00ab":
            out.append(t)
        elif out and out[-1] == "\u00ab":
            out[-1] += "\u00a0" + t
        else:
            out.append(t)
    return out


def cartons(phrase, cols=ST_COLS, lignes=ST_LIGNES):
    """Coupe une phrase en cartons de sous-titres.

    Programmation dynamique : on minimise d'abord le NOMBRE de cartons (moins
    de cartons = moins de changements a l'ecran), puis la longueur du plus long
    (ce qui les equilibre). Un decoupage glouton, lui, laisse un orphelin de
    deux mots en fin de phrase.
    """
    mots = mots_de(phrase)
    m = len(mots)
    if m == 0:
        return []
    INF = (10 ** 6, 10 ** 6)
    best = [INF] * m + [(0, 0)]
    coupe = [None] * (m + 1)
    for i in range(m - 1, -1, -1):
        for j in range(i + 1, m + 1):
            g = mots[i:j]
            if replie(g, cols, lignes) is None:
                break            # infaisable, et ca ne fera qu'empirer
            if best[j] == INF:
                continue
            cand = (best[j][0] + 1, max(len(" ".join(g)), best[j][1]))
            if cand < best[i]:
                best[i], coupe[i] = cand, j
        if coupe[i] is None:     # mot plus long que `cols` : on le sort seul
            coupe[i] = i + 1
            if best[i + 1] != INF:
                best[i] = (best[i + 1][0] + 1, max(len(mots[i]),
                                                   best[i + 1][1]))

    out, i = [], 0
    while i < m:
        j = coupe[i] or (i + 1)
        g = mots[i:j]
        out.append((" ".join(g), replie(g, cols, lignes) or [" ".join(g)]))
        i = j
    return out


# ----------------------------------------------------------------------------
# Construction de la bande son et de la piste de sous-titres
# ----------------------------------------------------------------------------
def bande_son(ep, diseur, pause_defaut=0.45, tete=0.6, queue=1.4):
    """Synthetise l'episode. Renvoie (echantillons, plans, cues)."""
    morceaux = [np.zeros(int(SR * tete), dtype=np.float32)]
    t = tete
    plans, cues = [], []

    for i, p in enumerate(ep["plans"]):
        t0 = t
        for ph in phrases(p["texte"]):
            s = diseur.dire(ph)
            d = len(s) / SR
            morceaux.append(s)
            # cartons repartis au prorata des caracteres de la phrase
            grp = cartons(ph)
            n = sum(len(g[0]) for g in grp) or 1
            tc = t
            for txt, lignes in grp:
                dc = d * len(txt) / n
                cues.append((tc, tc + dc, lignes))
                tc += dc
            t += d
            # petit souffle entre phrases d'un meme plan
            if len(phrases(p["texte"])) > 1:
                morceaux.append(np.zeros(int(SR * 0.18), dtype=np.float32))
                t += 0.18
        pause = float(p.get("pause", pause_defaut))
        dernier = (i == len(ep["plans"]) - 1)
        if not dernier:
            morceaux.append(np.zeros(int(SR * pause), dtype=np.float32))
            t += pause
        plans.append({"i": i, "t0": t0, "t1": t, "spec": p})

    morceaux.append(np.zeros(int(SR * queue), dtype=np.float32))
    t += queue
    if plans:
        plans[-1]["t1"] = t
    return np.concatenate(morceaux), plans, cues


def cale_duree(ep, diseur, verbeux=True):
    """Cale la duree totale sur la voix, en visant 60-90 s.
    N'ajoute jamais plus qu'un silence raisonnable : si la voix est trop
    courte, on le dit au lieu de gonfler la video de vide."""
    pause, queue = 0.45, 1.4
    son, plans, cues = bande_son(ep, diseur, pause, 0.6, queue)
    duree = len(son) / SR
    mini = float(ep.get("duree_min", CIBLE_MIN))
    maxi = float(ep.get("duree_max", CIBLE_MAX))

    if duree < mini:
        # on etire, mais avec un plafond : pause <= 2.2 s, queue <= 4 s
        manque = mini - duree
        trous = max(1, len(ep["plans"]) - 1)
        pause2 = min(2.2, pause + manque * 0.75 / trous)
        queue2 = min(4.0, queue + manque * 0.25)
        if (pause2, queue2) != (pause, queue):
            son, plans, cues = bande_son(ep, diseur, pause2, 0.6, queue2)
            duree = len(son) / SR
        if verbeux and duree < mini - 0.5:
            print("  ! duree %.1f s < cible %.0f s : le texte est trop court. "
                  "Ajoute des plans plutot que du silence." % (duree, mini))
    elif duree > maxi and verbeux:
        print("  ! duree %.1f s > cible %.0f s : coupe du texte." % (duree, maxi))
    return son, plans, cues, duree


def ecris_wav(chemin, s):
    x = np.clip(s, -1.0, 1.0)
    pcm = (x * 32767.0).astype("<i2")
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ----------------------------------------------------------------------------
# Sous-titres ASS
# ----------------------------------------------------------------------------
def hms(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def ecris_ass(chemin, cues):
    tete = """[Script Info]
ScriptType: v4.00+
PlayResX: %d
PlayResY: %d
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: O,%s,%d,&H00F2F2F2,&H000000FF,&H00000000,&HB4000000,-1,0,0,0,100,100,1,0,1,6,0,2,%d,%d,%d,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" % (L, H, POLICE_ASS, ST_TAILLE, MARGE - 12, MARGE - 12, ST_MARGE_BAS)

    lignes = []
    for i, (t0, t1, txt) in enumerate(cues):
        # pas de chevauchement, duree minimale lisible
        fin = t1
        if i + 1 < len(cues):
            fin = min(fin, cues[i + 1][0] - 0.01)
        if fin - t0 < 0.25:
            fin = t0 + 0.25
        corps = "\\N".join(txt).replace("{", "(").replace("}", ")")
        lignes.append("Dialogue: 0,%s,%s,O,,0,0,0,,%s" % (hms(t0), hms(fin), corps))
    Path(chemin).write_text(tete + "\n".join(lignes) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# Rendu des images
# ----------------------------------------------------------------------------
def battement(tg):
    """Pulsation : un battement par seconde, attaque nette, decroissance."""
    return math.exp(-5.0 * (tg % 1.0))


_captures = {}


def charge_capture(chemin, larg, haut):
    cle = (str(chemin), larg, haut)
    if cle in _captures:
        return _captures[cle]
    im = Image.open(chemin).convert("RGB")
    im.thumbnail((larg, haut), Image.LANCZOS)
    _captures[cle] = im
    return im


def ligne_registre(d, x0, x1, y, cle, val, taille, c_cle, c_val, gras_val=True):
    """Une ligne de registre comptable : cle .......... valeur"""
    f_cle = police(POLICE_R, taille)
    f_val = police(POLICE_B if gras_val else POLICE_R, taille)
    d.text((x0, y), cle, font=f_cle, fill=c_cle, anchor="lm")
    d.text((x1, y), val, font=f_val, fill=c_val, anchor="rm")
    a = x0 + d.textlength(cle, font=f_cle) + taille * 0.45
    b = x1 - d.textlength(val, font=f_val) - taille * 0.45
    pas = taille * 0.52
    x = a
    while x < b:
        d.text((x, y + taille * 0.04), ".", font=f_cle, fill=c_cle, anchor="lm")
        x += pas


def registre(ep, spec):
    """Les lignes du registre affiche par le visuel 'texte'."""
    r = spec.get("registre") or ep.get("registre")
    if r:
        return [(str(k), str(v)) for k, v in
                (r.items() if isinstance(r, dict) else r)]
    out = []
    if ep.get("solde"):
        out.append(("solde", str(ep["solde"])))
    if ep.get("variation"):        # jamais de chiffre non fourni (ligne rouge nº2)
        out.append(("variation", str(ep["variation"])))
    for l in (spec.get("lignes") or []):
        t = str(l)
        out.append(tuple(x.strip() for x in t.split("|", 1)) if "|" in t
                   else (t, ""))
    return out


def dessine(ep, plan, tg, fondu):
    """Une image complete. tg = temps global (s), fondu = 0..1 sur le visuel.

    Regle de composition : un seul compteur de solde a l'ecran a la fois,
    et c'est lui qui bat. Jamais deux fois la meme information.
    """
    img = Image.new("RGB", (L, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    bat = battement(tg)
    spec = plan["spec"]
    vis = spec.get("visuel", "texte")
    solde = str(ep.get("solde", ""))
    cy = (Y_VIS_0 + Y_VIS_1) // 2

    # --- entete : la piece, le nom, le jour
    f_ent = police(POLICE_B, 38)
    piece(d, MARGE + 19, Y_ENTETE, 19, (112, 112, 112))
    texte_espace(d, (MARGE + 58, Y_ENTETE), "OBOLE", f_ent, BLANC, espace=7,
                 ancre="lm")
    if ep.get("jour") is not None:
        texte_espace(d, (L - MARGE, Y_ENTETE), "JOUR %03d" % int(ep["jour"]),
                     f_ent, GRIS, espace=4, ancre="rm")
    d.line([(MARGE, Y_REGLE_H), (L - MARGE, Y_REGLE_H)], fill=GRIS_F, width=2)

    # --- zone du visuel
    if vis == "compteur":
        sous = spec.get("registre") or (
            [("variation", ep["variation"])] if ep.get("variation") else [])
        # sans ligne de registre, le bloc se recentre dans la zone
        dy = 0 if sous else 88
        texte_espace(d, (L // 2, cy - 205 + dy), "SOLDE", police(POLICE_R, 46),
                     att(GRIS, fondu), espace=16, ancre="mm")
        f = police(POLICE_B, int(round(172 * (1.0 + 0.034 * bat))))
        d.text((L // 2, cy - 45 + dy), solde, font=f,
               fill=att(BLANC, fondu * (0.86 + 0.14 * bat)), anchor="mm")
        d.line([(L // 2 - 260, cy + 90 + dy), (L // 2 + 260, cy + 90 + dy)],
               fill=att(GRIS_F, fondu), width=2)
        y = cy + 160
        x0, x1 = L // 2 - 250, L // 2 + 250
        for cle, val in sous:
            ligne_registre(d, x0, x1, y, str(cle), str(val), 42,
                           att((70, 70, 70), fondu), att(GRIS, fondu), False)
            y += 64

    elif vis == "capture":
        chem = spec.get("image")
        boite_l, boite_h = L - 2 * MARGE, 596
        y0 = Y_VIS_0 + 4
        if chem and Path(chem).exists():
            im = charge_capture(chem, boite_l - 16, boite_h - 16)
            px, py = (L - im.width) // 2, y0 + (boite_h - im.height) // 2
            if fondu < 0.999:
                im = Image.eval(im, lambda v: int(v * fondu))
            img.paste(im, (px, py))
            d.rectangle([px - 2, py - 2, px + im.width + 1, py + im.height + 1],
                        outline=att((96, 96, 96), fondu), width=2)
            leg = spec.get("legende") or ("capture r\u00e9elle \u2014 %s"
                                          % Path(chem).name)
        else:
            d.rectangle([MARGE, y0, L - MARGE, y0 + boite_h],
                        outline=att(GRIS_F, fondu), width=2)
            d.text((L // 2, y0 + boite_h // 2), "capture absente",
                   font=police(POLICE_R, 40), fill=att(GRIS, fondu), anchor="mm")
            leg = spec.get("legende") or "capture absente"
        d.text((L // 2, y0 + boite_h + 46), leg[:48], font=police(POLICE_R, 34),
               fill=att(GRIS, fondu), anchor="mm")

    else:  # "texte" : le registre du jour. Le propos est dans les sous-titres.
        lignes = registre(ep, spec)
        bl, br = MARGE + 54, L - MARGE - 54
        pas = 92
        hb = max(260 if len(lignes) < 2 else 352, 148 + pas * max(1, len(lignes)))
        by0 = cy - hb // 2
        d.rectangle([MARGE, by0, L - MARGE, by0 + hb],
                    outline=att((66, 66, 66), fondu), width=2)
        piece(d, bl + 17, by0 + 62, 17, att(GRIS, fondu * (0.3 + 0.7 * bat)))
        texte_espace(d, (bl + 56, by0 + 62), "REGISTRE", police(POLICE_R, 34),
                     att(GRIS, fondu), espace=9, ancre="lm")
        d.line([(bl, by0 + 104), (br, by0 + 104)],
               fill=att((66, 66, 66), fondu), width=2)
        y = by0 + 104 + (hb - 104) // (2 * len(lignes)) + 8
        for cle, val in lignes:
            bat_ici = cle.strip().lower() == "solde"
            t = int(round((66 if bat_ici else 50)
                          * (1.0 + (0.045 * bat if bat_ici else 0))))
            ligne_registre(
                d, bl, br, y, cle, val, t,
                att((96, 96, 96) if bat_ici else (74, 74, 74), fondu),
                att(BLANC, fondu * ((0.84 + 0.16 * bat) if bat_ici else 0.72)),
                bat_ici)
            y += pas

    # --- compteur compact : uniquement si le visuel ne le porte pas deja
    if vis == "capture" and solde:
        ligne_registre(d, MARGE, L - MARGE, Y_SOLDE_COMPACT, "solde", solde, 56,
                       (74, 74, 74), att(BLANC, 0.84 + 0.16 * bat), True)
    # --- avancement : le filet du bas est segmente, un segment par plan.
    # Sobre, et c'est une vraie information (ou on en est dans l'episode).
    n = max(1, len(ep.get("plans", [1])))
    ecart = 8 if n <= 20 else 4
    larg = (L - 2 * MARGE - ecart * (n - 1)) / n
    for k in range(n):
        x = MARGE + k * (larg + ecart)
        c = BLANC if k == plan["i"] else ((78, 78, 78) if k < plan["i"]
                                          else (34, 34, 34))
        d.rectangle([x, Y_REGLE_B - 2, x + larg, Y_REGLE_B + 2], fill=c)

    # --- pied : etiquetage IA (ligne rouge nº3 de identite.md)
    d.text((L // 2, Y_PIED), PIED, font=police(POLICE_R, 32),
           fill=(142, 142, 142), anchor="mm")
    return img


# ----------------------------------------------------------------------------
# Encodage
# ----------------------------------------------------------------------------
def mesure_loudnorm(wav):
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        return None
    try:
        return json.loads(m[-1])
    except Exception:
        return None


def filtre_audio(mes):
    base = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if mes:
        try:
            return (base + ":measured_I=%s:measured_TP=%s:measured_LRA=%s"
                    ":measured_thresh=%s:offset=%s:linear=true"
                    % (mes["input_i"], mes["input_tp"], mes["input_lra"],
                       mes["input_thresh"], mes.get("target_offset", "0.0")))
        except KeyError:
            pass
    return base


MENTION = ("Contenu g\u00e9n\u00e9r\u00e9 par intelligence artificielle (IA). "
           "Voix de synth\u00e8se. AI-generated content.")


def metadonnees(ep, moteur):
    """Etiquetage machine-detectable (AI Act art. 50, loi 2023-451).

    Pas de signature C2PA : elle exige un certificat que nous n'avons pas.
    Tags de conteneur standard uniquement, plus la mention incrustee a l'image.
    """
    t = {
        "title": ep.get("titre", "Obole"),
        "artist": "Obole (IA)",
        "album": "Le Journal d'Obole",
        "comment": MENTION,
        "description": MENTION,
        "synopsis": "Journal d'Obole \u2014 jour %s \u2014 solde %s. %s"
                    % (ep.get("jour"), ep.get("solde"), MENTION),
        "generator": "obole/episode.py + %s" % moteur,
        "software": "obole/episode.py + %s" % moteur,
        "ai_generated": "true",
        "synthetic_voice": moteur,
    }
    out = []
    for k, v in t.items():
        out += ["-metadata", "%s=%s" % (k, v)]
    return out


def rend(ep, plans, wav, ass, sortie, moteur, preset="veryfast", crf=20,
         verbeux=True):
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    mes = mesure_loudnorm(wav)
    if verbeux and mes:
        print("  loudnorm mesure : I=%s LUFS, TP=%s dBTP, LRA=%s"
              % (mes.get("input_i"), mes.get("input_tp"), mes.get("input_lra")))

    vf = "ass=%s,format=yuv420p" % str(ass).replace("\\", "/")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", "%dx%d" % (L, H), "-framerate", str(FPS), "-i", "-",
        "-i", str(wav),
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-tune", "stillimage", "-profile:v", "high", "-level", "4.2",
        "-g", str(FPS * 2), "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-af", filtre_audio(mes),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        # use_metadata_tags : sans lui, le muxeur mp4 jette les cles non
        # standard (generator, software...) au lieu de les ecrire dans udta.
        "-movflags", "+faststart+use_metadata_tags", "-shortest",
    ] + metadonnees(ep, moteur) + [str(sortie)]
    t0 = time.time()
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n_total = 0
    try:
        for plan in plans:
            duree = plan["t1"] - plan["t0"]
            n = max(1, int(round(duree * FPS)))
            cache = {}
            for i in range(n):
                tl = i / FPS
                tg = plan["t0"] + tl
                fondu = min(1.0, max(0.0, tl / 0.28))
                if plan is plans[-1]:
                    pass
                else:
                    fondu *= min(1.0, max(0.0, (duree - tl) / 0.22))
                cle = (int(round((tg % 1.0) * FPS)) % FPS, round(fondu * 8))
                buf = cache.get(cle)
                if buf is None:
                    buf = dessine(ep, plan, tg, fondu).tobytes()
                    cache[cle] = buf
                pr.stdin.write(buf)
                n_total += 1
            cache.clear()
        pr.stdin.close()
    except BrokenPipeError:
        pass
    code = pr.wait()
    if code != 0:
        raise RuntimeError("ffmpeg a echoue (code %d)" % code)
    return time.time() - t0, n_total


# ----------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------
def sonde(mp4):
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(mp4)],
                       stdout=subprocess.PIPE, text=True, check=True)
    return json.loads(p.stdout)


def controle(mp4, n=3):
    """Extrait n images fixes pour verifier le rendu a l'oeil."""
    info = sonde(mp4)
    d = float(info["format"]["duration"])
    dossier = Path(mp4).parent / "controle"
    dossier.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(n):
        t = d * (i + 0.5) / n
        f = dossier / ("%s-%02d.png" % (Path(mp4).stem, i + 1))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t,
                        "-i", str(mp4), "-frames:v", "1", str(f)], check=True)
        out.append((t, f))
    return out


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Genere un episode video d'Obole.")
    ap.add_argument("json", help="fichier JSON de l'episode")
    ap.add_argument("--sortie", help="chemin du mp4 (sinon champ 'sortie' du JSON)")
    ap.add_argument("--voix", default="auto", choices=["auto", "kokoro", "edge"])
    ap.add_argument("--nom-voix", default=None,
                    help="ff_siwis (kokoro) ou fr-FR-HenriNeural (edge)")
    ap.add_argument("--vitesse", type=float, default=1.0)
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--sans-cache", action="store_true",
                    help="ignore le cache de synthese vocale")
    ap.add_argument("--controle", type=int, default=0,
                    help="extrait N images fixes de controle")
    ap.add_argument("--garder", action="store_true",
                    help="conserve le wav et l'ass a cote du mp4")
    a = ap.parse_args()

    ep = json.loads(Path(a.json).read_text(encoding="utf-8"))
    sortie = a.sortie or ep.get("sortie") or "media/episodes/episode.mp4"
    sortie = Path(sortie)
    if not sortie.is_absolute():
        sortie = RACINE / sortie

    # les chemins d'image relatifs se lisent depuis la racine du projet
    for p in ep.get("plans", []):
        if p.get("image"):
            q = Path(p["image"])
            p["image"] = str(q if q.is_absolute() else RACINE / q)

    print("== %s" % ep.get("titre", sortie.name))
    voix = fabrique_voix(a.voix, a.vitesse, a.nom_voix)
    diseur = Diseur(voix, cache=not a.sans_cache)
    print("  voix : %s / %s" % (voix.nom, getattr(voix, "voix", "?")))

    son, plans, cues, duree = cale_duree(ep, diseur)
    if diseur.secondes_synthetisees > 0:
        print("  synthese : %.1f s de calcul pour %.1f s d'audio neuf "
              "(x%.2f temps reel), %d segments en cache"
              % (diseur.temps_synthese, diseur.secondes_synthetisees,
                 diseur.secondes_synthetisees / diseur.temps_synthese,
                 diseur.touches))
    else:
        print("  synthese : tout en cache (%d segments)" % diseur.touches)
    print("  duree visee : %.2f s, %d plans, %d cartons de sous-titres"
          % (duree, len(plans), len(cues)))

    tmp = Path(tempfile.mkdtemp(prefix="obole-"))
    wav, ass = tmp / "voix.wav", tmp / "sous.ass"
    ecris_wav(wav, son)
    ecris_ass(ass, cues)

    moteur = voix.libelle()
    t_rendu, n_img = rend(ep, plans, wav, ass, sortie, moteur, a.preset, a.crf)
    info = sonde(sortie)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    au = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    taille = Path(sortie).stat().st_size

    print("  rendu : %.1f s pour %d images (%.1f img/s), x%.2f temps reel"
          % (t_rendu, n_img, n_img / t_rendu, (n_img / FPS) / t_rendu))
    print("  -> %s" % sortie)
    print("     %sx%s, %s, %.2f s, %.1f Mo, audio %s %s Hz"
          % (v["width"], v["height"], v["codec_name"],
             float(info["format"]["duration"]), taille / 1e6,
             au["codec_name"] if au else "-",
             au["sample_rate"] if au else "-"))

    tags = sonde(sortie)["format"].get("tags", {})
    print("  metadonnees IA : %s" % ", ".join(sorted(tags)))
    for k in ("comment", "generator", "ai_generated"):
        if k in tags:
            print("     %-13s %s" % (k, tags[k][:78]))

    if a.controle:
        for t, f in controle(sortie, a.controle):
            print("     controle t=%.1fs -> %s" % (t, f))
    if a.garder:
        shutil.copy(wav, Path(sortie).with_suffix(".wav"))
        shutil.copy(ass, Path(sortie).with_suffix(".ass"))
        print("     wav et ass conserves a cote du mp4")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
