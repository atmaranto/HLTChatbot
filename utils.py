import nltk, sys, code, traceback
import requests.exceptions
from nltk import pos_tag, word_tokenize, sent_tokenize
from nltk.tokenize.treebank import TreebankWordDetokenizer
from nltk.corpus import wordnet as wn
from nltk.stem import WordNetLemmatizer
from corenlp import parser
from tqdm import tqdm
import sqlite3

def better_sent_tokenize(texts):
    if isinstance(texts, (str, bytes)):
        texts = [texts]
    
    sents = []
    
    for text in texts:
        for sent in sent_tokenize(text):
            if len(sent) > 100 and '\n' in sent:
                sents.extend(s.strip() for s in sent.split("\n") if s.strip())
            else:
                sents.append(sent)
    
    return sents

def collect_nps(tree):
    s = set()
    
    for item in tree:
        if isinstance(item, (bytes, str)): continue
        
        if item.label() in ("NP",):
            s.add(item)
        elif item.label() not in ("VP",):
            s.update(collect_nps(item))
    
    return s

def find_node_by_tag(tree, tags, which=1, recursive=False):
    if not isinstance(tags, (tuple, list)) and not callable(tags):
        tags = (tags,)
    
    counter = 0
    
    while len(tree) > 0:
        for node in tree:
            if (callable(tags) and tags(node.label())) or (not callable(tags) and node.label() in tags):
                counter += 1
                if counter >= which:
                    return node
        
        if not recursive: break
        
        newtree = []
        for node in tree:
            if isinstance(node, nltk.tree.Tree):
                newtree.extend([item for item in node if not isinstance(item, (str, bytes))])
        tree = newtree
    
    return None

def _collect_vps2(tree):
    """Looks for S tags recursively."""
    for node in tree:
        if isinstance(node, (str, bytes)):
            continue
        
        if node.label() in ("S",):
            for inner in collect_vps(node): yield inner
        else:
            for inner in _collect_vps2(node): yield inner

def clean_dts(node):
    for i in range(len(node)):
        if node[i].label() == "DT":
            node.pop(i)
            break
    
    return node

def replace_prp(node, it, origin):
    if it is None: return node
    
    for i in range(len(node)):
        item = node[i]
        if isinstance(item, (str, bytes)): continue
        
        if item.label() == "PRP":
            node[i] = it.copy()
        elif ' '.join(item.leaves()) in ('game', 'video game'):
            node[i] = origin.copy()
        else:
            node[i] = replace_prp(item, it, origin)
    
    return node

class _Pointer:
    def __init__(self, ptr=None):
        self.ptr = ptr
        self.origin = ptr

twd = TreebankWordDetokenizer()

def detokenize(tokens):
    return twd.detokenize(tokens)

def capitalize_all(s):
    return detokenize([word.capitalize() for word in word_tokenize(s)])

def collect_vps(tree, ptr=None):
    ptr = ptr or _Pointer() # Keeps track of last NP for pronouns
    np = None
    vp = None
    
    for node in tree:
        if isinstance(node, (str, bytes)): continue
        
        if node.label() in ("S",):
            for inner in collect_vps(node, ptr): yield inner
            
            np = None
            vp = None
        else:
            if node.label() in ("NP",):
                node = clean_dts(node)
                node = replace_prp(node, ptr.ptr, ptr.origin)
                
                if np is not None:
                    # print("Warning: adjacent NPs.", file=sys.stderr)
                    # print(tree, file=sys.stderr)
                    np = nltk.tree.Tree("NP", [np, node])
                else:
                    np = node
                
                ptr.ptr = np
                vp = None

                #for inner in collect_vps(node, ptr): yield inner
            elif node.label() in ("VP",):
                if np is None: continue # This is alright, I think; we just ignore it
                if vp is not None:
                    print("Warning: adjacent VPs.", file=sys.stderr)
                    print(tree, file=sys.stderr)
                
                vp = node
                pred = None
                obj = None
                extra = ''
                
                for nd in node:
                    if isinstance(nd, (str, bytes)): continue
                    
                    if nd.label().startswith("VB"):
                        pred = detokenize(nd.leaves())
                    elif nd.label() in ("NP") and obj is None:
                        obj = nd
                    elif nd.label() in ("PP",) and obj is None:
                        obj = nd.copy()
                        for i in range(len(obj)):
                            if obj[i].label() in ("IN", "TO"):
                                extra = detokenize(obj[i].leaves())
                                obj.pop(i)
                                break
                    
                    if pred is not None and obj is not None: break
                else:
                    # print("Warning: no VB or obj found in VP", file=sys.stderr)
                    # print(tree)
                    continue

                obj = detokenize(obj.leaves())
                
                for one_np in {np.freeze()} | collect_nps(np.freeze()):
                    subject = detokenize(one_np.leaves())
                    if subject.strip() == '': continue
                    
                    yield subject, pred, obj, extra, node
                np = None
            else:
                for inner in collect_vps(node, ptr): yield inner

wnl = WordNetLemmatizer()

def advanced_parse(sent : str):
    result = parser.api_call(sent, # "The end of the world is upon us, and Mario Kart 3 won't help."
                             properties={"annotators": "tokenize,ssplit,pos,parse,ner,openie"})
    
    sent = result["sentences"][0]
    return parser.make_tree(sent), sent.get("entitymentions", []), sent["openie"], sent["tokens"]

#[{'docTokenBegin': 10, 'docTokenEnd': 12, 'tokenBegin': 10, 'tokenEnd': 12, 'text': 'Mario Kart', 'characterOffsetBegin': 37, 'characterOffsetEnd': 47, 'ner': 'PERSON', 'nerConfidences': {'PERSON': 0.72344230621544}}, {'docTokenBegin':
# 12, 'docTokenEnd': 13, 'tokenBegin': 12, 'tokenEnd': 13, 'text': '3', 'characterOffsetBegin': 48, 'characterOffsetEnd': 49, 'ner': 'NUMBER', 'normalizedNER': '3.0', 'nerConfidences': {'NUMBER': -1}}]

def collect_relations(sent, title="game"):
    relations = []
    try:
        tree, entities, openie, tokens = advanced_parse(sent)
    except requests.exceptions.HTTPError as e:
        print(f"API call failed for sentence: {sent}")
        traceback.print_exc()
        return relations
    
    replace_with_title = ("it", "game")
    
    # Disabled because it was performing poorly
    if False:
        for entry in openie:
            relation = entry["relation"]
            
            original_phrase = ' '.join((entry["subject"], entry["relation"], entry["object"]))
            
            verb, verb_pos = None, None
            for i, (word, tag) in enumerate(pos_tag(word_tokenize(relation))):
                if tag.startswith("VB"):
                    verb = i
                    verb_pos = tag
                    break
            else:
                continue
            verb = verb + entry["relationSpan"][0]
            
            extras = []
            for i in range(*entry["relationSpan"]):
                if i != verb:
                    extras.append(tokens[i]["word"])
            extra_s = ' '.join(extras)
            
            relation_lemma = tokens[verb]["lemma"] # wnl.lemmatize(tokens[verb]["word"], "v")
            
            for key in ("subject", "object"):
                if entry[key].lower() in replace_with_title:
                    entry[key] = title
            
            relations.append({
                "subject": entry["subject"],
                "relation": relation_lemma,
                "object": entry["object"],
                "original_phrase": original_phrase,
                "extra": extra_s
            })
    
    for np, predicate, other, extra, upper in collect_vps(tree, _Pointer(nltk.tree.Tree("NP", [title]))):
        relations.append({
            "subject": np.lower(),
            "relation": wnl.lemmatize(next((word for word, tag in pos_tag(word_tokenize(predicate)) if tag.startswith("VB")), predicate), "v").lower(),
            "object": other.lower(),
            "original_phrase": detokenize(upper.leaves()),
            "extra": extra
        })
    
    return relations

def preprocess_db(con : sqlite3.Connection, cur : sqlite3.Cursor):
    # TODO: Mark "there be" as existential
    # cur.execute("DROP TABLE IF EXISTS relations;")
    cur.execute("CREATE TABLE IF NOT EXISTS relations ("
                "  subject TEXT NOT NULL,"
                "  relation TEXT NOT NULL,"
                "  object TEXT NOT NULL,"
                "  original_phrase TEXT NOT NULL," # Original phrase
                "  extra TEXT," # Optional extra text
                "  game_id INT NOT NULL," # Optional game_id
                "  franchise_id INT," # Optional franchise id
                "  PRIMARY KEY(subject, relation, object, game_id)"
                ");")
    
    relations = []
    added = set()
    
    for (game_id, name, summary, story) in tqdm(list(cur.execute("SELECT id, name, summary, story FROM games;")), unit="sent"):
        for sent in better_sent_tokenize([summary, story]):
            if not sent.strip(): continue # Ignore blank text
            
            for entry in collect_relations(sent, name):
                key = (entry["subject"], entry["relation"], entry["object"], game_id)
                if key not in added:
                    relations.append({**entry, "game_id": game_id, "franchise_id": None})
                    added.add(key)
    
    try:
        cur.executemany("INSERT INTO relations (subject, relation, object, extra, original_phrase, game_id, franchise_id) "
                        "SELECT :subject, :relation, :object, :extra, :original_phrase, :game_id, :franchise_id "
                        "WHERE NOT EXISTS(SELECT * FROM relations WHERE"
                        "                 subject  LIKE :subject  AND "
                        "                 relation LIKE :relation AND "
                        "                 object   LIKE :object   AND "
                        "                 game_id     = :game_id"
                        "                )",
                        relations)
        
        con.commit()
    except Exception as e:
        traceback.print_exc()
    
    code.interact(local=locals())
