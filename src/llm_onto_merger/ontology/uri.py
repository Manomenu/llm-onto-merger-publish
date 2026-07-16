from rdflib import URIRef


def local_name(uri: URIRef | str) -> str:
    """Return the local fragment of a URI (after # or last /)."""
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rsplit("/", 1)[-1]


def namespace_of(uri: str) -> str:
    """Return the namespace prefix of a URI, or '' if none can be determined.

    A valid namespace must have a non-empty local part and be longer than a
    bare scheme (http:// = 7 chars) so that URIs like 'http://cmt' do not
    produce the nonsense prefix 'http://'.
    """
    ns = (uri.rsplit("#", 1)[0] + "#") if "#" in uri else (uri.rsplit("/", 1)[0] + "/")
    return ns if len(uri) > len(ns) and len(ns) > 8 else ""
