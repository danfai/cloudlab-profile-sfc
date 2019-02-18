#!/usr/bin/env python2.7
"""
This profile uses a git repository based configuration
"""

import re
import geni.aggregate.cloudlab as cloudlab
import geni.portal as portal
import geni.rspec.emulab as emulab
import geni.rspec.pg as pg
import geni.urn as urn

# Portal context is where parameters and the rspec request is defined.
pc = portal.Context()

# The possible set of base disk-images that this cluster can be booted with.
# The second field of every tupule is what is displayed on the cloudlab
# dashboard.
images = [ ("UBUNTU16-64-STD", "Ubuntu 16.04") ]

# The possible set of node-types this cluster can be configured with. Currently
# only m510 machines are supported.
hardware_types = [ ("m510", "m510 (CloudLab Utah, 8-Core Intel Xeon D-1548)")
                   #,("d430", "d430 (Emulab, 8-Core Intel Xeon E5-2630v3)")
                   ]

# Create a portal context.
pc = portal.Context()

pc.defineParameter("image", "Disk Image",
        portal.ParameterType.IMAGE, images[0], images,
        "Specify the base disk image that all the nodes of the cluster " +\
        "should be booted with.")

pc.defineParameter("hardware_type", "Hardware Type",
       portal.ParameterType.NODETYPE, hardware_types[0], hardware_types)

pc.defineParameter("username", "Username",
        portal.ParameterType.STRING, "", None,
        "Username of cloudlab account.")

# Default the cluster size to 5 nodes (minimum requires to support a
# replication factor of 3 and an independent coordinator).
#pc.defineParameter("num_worker", "Cluster Size (# workers)",
#        portal.ParameterType.INTEGER, 4, [],
#        "Specify the number of worker servers. Note that the total " +\
#        "number of servers in the experiment will be this number + #num_sff + 1 " +\
#        "(one additional server which acts as a jumphost ). To check " +\
#        "availability of nodes, visit " +\
#        "\"https://www.cloudlab.us/cluster-graphs.php\"")

#
pc.defineParameter("num_sff", "Number of Service Function Forwarder and sites",
        portal.ParameterType.INTEGER, 1, [],
        "Specify the number service functions forwarder." )

pc.defineParameter("num_sf_per_sff", "Number of Hosts with service functions per sites",
        portal.ParameterType.INTEGER, 3, [],
        "Specify the number service functions per site." )

pc.defineParameter("latency_local", "Latency of the network per site (SFF-SF communication, in ms)",
    portal.ParameterType.INTEGER, 2, [],
    "Specify the latency of all in-site connections. (Used for SFF-SF communication)")

pc.defineParameter("latency_remote", "Latency of the out of site communication (SFF-SFF, in ms)",
    portal.ParameterType.INTEGER, 3, [],
    "Specify the latency of all off-site connections. This will be used for SFF to SFF communications.")

pc.defineParameter("bw_local", "Link capacity of in-site connections",
    portal.ParameterType.INTEGER, 5000, [],
    "Specify the link capacity of all in-site connections. (Used for SFF-SF communication). ")

pc.defineParameter("bw_remote", "Link capacity of off-site links",
    portal.ParameterType.INTEGER, 2500, [],
    "Specify the link capacity of off-site connections. This will be used for SFF to SFF communications")

# Size of partition to allocate for local disk storage.
pc.defineParameter("local_storage_size", "Size of Node Local Storage Partition",
        portal.ParameterType.STRING, "40GB", [],
        "Size of local disk partition to allocate for node-local storage.")

# Size of partition to allocate for NFS shared home directories.
pc.defineParameter("nfs_storage_size", "Size of NFS Shared Storage",
        portal.ParameterType.STRING, "60GB", [],
        "Size of disk partition to allocate on NFS server.")

# Datasets to connect to the cluster (shared via NFS).
pc.defineParameter("dataset_urns", "datasets",
        portal.ParameterType.STRING, "", None,
        "Space separated list of datasets to mount. All datasets are " +\
        "first mounted on the NFS server at /remote, and then mounted via " +\
        "NFS on all other nodes at /datasets/dataset-name")

params = pc.bindParameters()

if params.num_sf_per_sff < 1:
    portal.context.reportError( portal.ParameterError( "num_sf_per_sff should be >= 1." ) )

if params.num_sff < 1:
    portal.context.reportError( portal.ParameterError( "num_sff should be >= 1" ) )

# Create a Request object to start building the RSpec.
request = pc.makeRequestRSpec()

# Create a dedicated network for the experiment
sff_lans = []
for i in range(params.num_sff):
    testlan = request.LAN("local_sff%02d" % (i+1))
    testlan.best_effort = True
    testlan.vlan_tagging = True
    testlan.link_multiplexing = True
    testlan.trivial_ok = False
    testlan.bandwidth = params.bw_local
    testlan.latency = 0.001 * params.latency_local
    sff_lans.append(testlan)

remote = request.LAN("remote_sff_net")
remote.best_effort = True
remote.vlan_tagging = True
remote.link_multiplexing = True
remote.trivial_ok = False
remote.bandwidth = params.bw_remote
remote.latency = 0.001 * params.latency_remote

# Create a special network for connecting datasets to the nfs server.
dslan = request.LAN("dslan")
dslan.best_effort = True
dslan.vlan_tagging = True
dslan.link_multiplexing = True


# Create array of the requested datasets
dataset_urns = []
if (params.dataset_urns != ""):
    dataset_urns = params.dataset_urns.split(" ")

nfs_shared_home_export_dir = "/local/nfs"
nfs_datasets_export_dir = "/remote"

# Add datasets to the dataset-lan
for i in range(len(dataset_urns)):
    dataset_urn = dataset_urns[i]
    dataset_name = dataset_urn[dataset_urn.rfind("+") + 1:]
    rbs = request.RemoteBlockstore(
            "dataset%02d" % (i + 1),
            nfs_datasets_export_dir + "/" + dataset_name,
            "if1")
    rbs.dataset = dataset_urn
    dslan.addInterface(rbs.interface)

# Setup node names
HOSTNAME_JUMPHOST = "jumphost"
#HOSTNAME_EXP_CONTROLLER = "expctrl"

node_local_storage_dir = "/dev/xvdca"

hostnames = []
sffs = []
for i in range(params.num_sff):
    hostnames.append("sff-%02d" % (i + 1))
    sffs.append("sff-%02d" % (i + 1))
    for j in range(params.num_sf_per_sff):
        hostnames.append("sf-%02d-%02d" % ((i + 1) , (j + 1)))

hostnames += [HOSTNAME_JUMPHOST]

# Setup the cluster one node at a time.
for idx, host in enumerate(hostnames):
    node = request.RawPC(host)
    node.hardware_type = params.hardware_type
    node.disk_image = urn.Image(cloudlab.Utah, "emulab-ops:%s" % params.image)

    if (host == HOSTNAME_JUMPHOST):
        # public ipv4
        node.routable_control_ip = True

        nfs_bs = node.Blockstore(host + "_nfs_bs", nfs_shared_home_export_dir)
        nfs_bs.size = params.nfs_storage_size

        dslan.addInterface(node.addInterface("if2"))
    else:
        # NO public ipv4
        node.routable_control_ip = False


    node.addService(pg.Execute(shell="sh",
        command="sudo /local/repository/system-setup.sh %s %s %s %s %s %s" % \
        (node_local_storage_dir, params.username,
        params.num_sff, params.num_sf_per_sff, nfs_shared_home_export_dir, nfs_datasets_export_dir)))

    # All nodes in the cluster connect to clan.
    n_iface = node.addInterface("local_lan")
    if (host not in [HOSTNAME_JUMPHOST]):
        sff_lans[int(idx/params.num_sf_per_sff)].addInterface(n_iface)
    else:
        core.addInterface(n_iface)

    # add sff-sff LAN
    if (host in sffs):
        rem_iface = node.addInterface("sff_lan")
        remote_lan.addInterface(rem_iface)

    if (host != HOSTNAME_JUMPHOST):
        local_storage_bs = node.Blockstore(host + "_local_storage_bs",
            node_local_storage_dir)
        local_storage_bs.size = params.local_storage_size

# Print the RSpec to the enclosing page.
pc.printRequestRSpec(request)
