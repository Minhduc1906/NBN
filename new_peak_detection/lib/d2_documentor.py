class mininet_documentor():
    def __init__(self, topo):
        print(topo.ports)

        with open('readme.txt', 'w') as f:
            f.write('Create a new text file!')
        exit()
