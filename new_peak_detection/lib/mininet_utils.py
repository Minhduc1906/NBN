import os

class mininet_utils:
    def __init__(self, parent_directory, test_name):
        self.parent_directory = os.path.join(parent_directory, test_name)
        self.test_name = test_name

    def create_directories(self):
        directories = ['', 'raw', 'documentation', 'graphs', 'pcaps']
  
        parent_dir = self.parent_directory
        for directory in directories:
            path = os.path.join(parent_dir, directory)
            try:
                if not os.path.exists(os.path.dirname(path)):
                    os.makedirs(os.path.dirname(path))
            except OSError as err:
                print(err)

    def create_topology_diagram(self, topo):
        sorted_dict = []
        for node, link in topo.ports.items():
            for links, n in link.items():
                sList = tuple(sorted([str(node + ':' + str(links)), str(n[0] + ':' + str(n[1]))]))
                sorted_dict.append(sList)
        deduplicated_list = list(dict.fromkeys(sorted_dict))
        d2_file = os.path.join(self.parent_directory, self.test_name) + '.d2' 
        svg_file = os.path.join(self.parent_directory, self.test_name) + '.svg' 
        png_file = os.path.join(self.parent_directory, self.test_name) + '.png' 
        with open(d2_file, 'w') as f:
            #[('s1:1', 's2:1'), ('s1:2', 's3:1'), ('s2:2', 's4:1'), ('h1:0', 's3:2'), ('h3:0', 's3:3'), ('h2:0', 's4:2'), ('h4:0', 's4:3')]
            for links in deduplicated_list:
                source_node = links[0].split(':')[0]
                source_link = links[0].split(':')[1]
                dest_node = links[1].split(':')[0]
                dest_link = links[1].split(':')[1]
                f.write(source_node + ' <-> ' + dest_node + ': {' +
                    '\nsource-arrowhead.label:' + source_link +
                    '\ntarget-arrowhead.label:' + dest_link +
                    '\n}\n')
        #commands = ['/usr/local/bin/d2 ' + d2_file + ' ' + svg_file, '/usr/local/bin/d2 ' + d2_file + ' ' + png_file]
        commands = ['/usr/local/bin/d2 ' + d2_file + ' ' + svg_file]
        for command in commands:
            os.system(command)
