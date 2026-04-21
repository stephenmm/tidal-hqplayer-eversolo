import tidalapi


def fmt_track(t: tidalapi.Track) -> dict:
    return {
        "id":       t.id,
        "title":    t.name,
        "artist":   t.artist.name if t.artist else "",
        "album":    t.album.name  if t.album  else "",
        "duration": t.duration,
        "quality":  str(t.audio_quality) if hasattr(t, "audio_quality") else "",
    }


def fmt_album(a: tidalapi.Album) -> dict:
    return {
        "id":     a.id,
        "title":  a.name,
        "artist": a.artist.name if a.artist else "",
        "year":   a.year,
        "cover":  a.image(320) if hasattr(a, "image") else None,
    }
