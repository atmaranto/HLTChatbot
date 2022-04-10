# A test script that runs the input through CoreNLP through NLTK

import atexit, sys, os, code
from nltk.parse.corenlp import CoreNLPServer, CoreNLPParser
from nltk import word_tokenize

print("Loading CoreNLP Server...")

config_file = "corenlp.pth"
if not os.path.isfile(config_file):
    warning_msg = f"Warning: {config_file} does not exist. Hopefully, the required jarfiles for Stanford CoreNLP are in the path. " + \
                  f"Otherwise, please download them from https://stanfordnlp.github.io/CoreNLP/download.html and put the paths to " + \
                  f"stanford-corenlp-X.X.X.jar and stanford-corenlp-X.X.X-models.jar as the first two lines of corenlp.pth."
    print(warning_msg, file=sys.stderr)
    corenlp_server = None
    corenlp_models = None
else:
    with open(config_file, "r") as f:
        corenlp_server = f.readline().strip()
        corenlp_models = f.readline().strip()

corenlp_options = ["-preload", "tokenize,ssplit,pos,lemma,parse,depparse,ner,openie"]

server = CoreNLPServer(corenlp_server, corenlp_models, corenlp_options=corenlp_options)
server.start() #(open("stdout.log", "wb"), open("stderr.log", "wb"))
atexit.register(server.stop)

parser = CoreNLPParser(server.url)

# item = list(parser.parse(word_tokenize("The end of the world is upon us, and Mario Kart 3 won't help.")))[0]

if __name__ == "__main__":
    if 'interact' in sys.argv:
        code.interact(local=locals())
    else:
        print("Enter sentences to be parsed")
        while True:
            for i, tree in enumerate(parser.parse(word_tokenize(input("> ")))):
                print(f"Tree {i+1}:")
                print(tree)
