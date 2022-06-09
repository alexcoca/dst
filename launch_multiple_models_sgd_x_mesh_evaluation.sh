#!/bin/bash
#!
#! Example SLURM job script for Wilkes3 (AMD EPYC 7763, ConnectX-6, A100)
#! Last updated: Fri 30 Jul 11:07:58 BST 2021
#!

#!#############################################################
#!#### Modify the options in this section as appropriate ######
#!#############################################################

#! sbatch directives begin here ###############################
#! Name of the job:
#SBATCH -J sgd_x_decoding
#! Which project should be charged (NB Wilkes2 projects end in '-GPU'):
#SBATCH -A BYRNE-SL3-GPU
#! How many whole nodes should be allocated?
#SBATCH --nodes=1
#! How many (MPI) tasks will there be in total?
#! Note probably this should not exceed the total number of GPUs in use.
#SBATCH --ntasks=1
#! Specify the number of GPUs per node (between 1 and 4; must be 4 if nodes>1).
#! Note that the job submission script will enforce no more than 32 cpus per GPU.
#SBATCH --gres=gpu:1
#! How much wallclock time will be required?
#SBATCH --time=0:30:00
#! What types of email messages do you wish to receive?
#SBATCH --mail-type=NONE
#SBATCH --array=0-5
#! Uncomment this to prevent the job from being requeued (e.g. if
#! interrupted by node failure or system downtime):
##SBATCH --no-requeue

#! Do not change:
#SBATCH -p ampere

#! sbatch directives end here (put any additional directives above this line)

#! Notes:
#! Charging is determined by GPU number*walltime.

#! Number of nodes and tasks per node allocated by SLURM (do not change):
numnodes=$SLURM_JOB_NUM_NODES
numtasks=$SLURM_NTASKS
mpi_tasks_per_node=$(echo "$SLURM_TASKS_PER_NODE" | sed -e  's/^\([0-9][0-9]*\).*$/\1/')
#! ############################################################
#! Modify the settings below to specify the application's environment, location
#! and launch method:

#! Optionally modify the environment seen by the application
#! (note that SLURM reproduces the environment at submission irrespective of ~/.bashrc):
. /etc/profile.d/modules.sh                # Leave this line (enables the module command)
module purge                               # Removes all modules still loaded
module load rhel8/default-amp              # REQUIRED - loads the basic environment

if [ -z ${CONDA_ENV_PATH+x} ]; then
  echo "Please pass the absolute path to your conda environment by prepending CONDA_ENV_PATH=abs/path/to/the/args variable."
  exit
fi

if [ -z ${CRS+x} ]; then
  echo "Please enter your CRS. For example prepend CRS=ac2123"
  exit
fi

#! Insert additional module load commands after this line if needed:
module load python/3.8
module load miniconda/3
eval "$(conda shell.bash hook)"
conda activate "$CONDA_ENV_PATH"
which python


VERSION="${VERSIONS[$SLURM_ARRAY_TASK_ID]}"
if [ -z ${CHECKPOINT_DIRS+x} ]; then
  echo "Please pass the path to the directory of the checkpoint you want to run inference on by prepending
  CHECKPOINT_DIRS=abs/path/to/the/args to your command. This should end in */checkpoint-[STEP]."
  exit
fi
if [ -z ${VERSIONS+x} ]; then
  echo "Please specify the version of the data you want to run inference for by prepending VERSIONS=int to the command.
  For example, to run inference on version 1 pass prepend VERSIONS=1. This should match the /version_*/ portion of
  CHECKPOINT_DIRS"
  exit
fi
if [ -z ${SHARDS+x} ]; then
  echo "Please specify which SGD versions you would like to test on by prepending an array SHARDS= to the command.
  For example, if you are decoding one model on original and v1 dataset the prepend SHARDS='original v1'. The len of
  this array must be equal to the len of CHECKPOINT_DIRS and VERSIONS"
  exit
fi

CHECKPOINT_DIRS=($CHECKPOINT_DIRS)
VERSIONS=($VERSIONS)
SHARDS=($SHARDS)
NUMBER_OF_MODELS="${#CHECKPOINT_DIRS[@]}"
NUMBER_OF_VERSIONS="${#VERSIONS[@]}"
NUMBER_OF_SHARDS="${#SHARDS[@]}"
if [ "$NUMBER_OF_MODELS" -ne "$NUMBER_OF_VERSIONS" ]; then
  echo "Number of models is $NUMBER_OF_MODELS but only got $NUMBER_OF_VERSIONS in the data versions array so cannot determine version. Aborting."
  exit
fi
if [ "$NUMBER_OF_SHARDS" -ne "$NUMBER_OF_MODELS" ]; then
  echo "You have specified $NUMBER_OF_SHARDS SGD-X variants and $NUMBER_OF_MODELS models. Please specify which SGD-X variant should be decoded for each position in the CHECKPOINT_DIRS array"
  exit
fi

SGD_SHARD=${SHARDS[$SLURM_ARRAY_TASK_ID]}
CHECKPOINT_DIR="${CHECKPOINT_DIRS[$SLURM_ARRAY_TASK_ID]}"
VERSION="${VERSIONS[$SLURM_ARRAY_TASK_ID]}"

#! Full path to application executable:
application="python -u -m scripts.batch_decode"

#! Run options for the application:
options="-t /home/$CRS/rds/rds-wjb31-nmt2020/ac2123/d3st/data/preprocessed/$SGD_SHARD/test/version_$VERSION/data.json \
-a /home/ac2123/rds/rds-wjb31-nmt2020/ac2123/d3st/configs/hpc_decode_arguments.yaml \
-s /home/ac2123/rds/hpc-work/dstc8-schema-guided-dialogue/sgd_x/data/original/train/schema.json \
-c $CHECKPOINT_DIR \
-hyp /home/$CRS/rds/rds-wjb31-nmt2020/ac2123/d3st/hyps -vvv --test"

#! Work directory (i.e. where the job will run):
workdir="$SLURM_SUBMIT_DIR"  # The value of SLURM_SUBMIT_DIR sets workdir to the directory
                             # in which sbatch is run.

#! Are you using OpenMP (NB this is unrelated to OpenMPI)? If so increase this
#! safe value to no more than 128:
export OMP_NUM_THREADS=1

#! Number of MPI tasks to be started by the application per node and in total (do not change):
np=$[${numnodes}*${mpi_tasks_per_node}]

#! Choose this for a pure shared-memory OpenMP parallel program on a single node:
#! (OMP_NUM_THREADS threads will be created):
CMD="$application $options"

#! Choose this for a MPI code using OpenMPI:
#CMD="mpirun -npernode $mpi_tasks_per_node -np $np $application $options"


###############################################################
### You should not have to change anything below this line ####
###############################################################

cd "$workdir"
echo -e "Changed directory to $(pwd).\n"

JOBID=$SLURM_JOB_ID

echo -e "JobID: $JOBID\n======"
echo "Time: $(date)"
echo "Running on master node: $(hostname)"
echo "Current directory: $(pwd)"

if [ "$SLURM_JOB_NODELIST" ]; then
        #! Create a machine file:
        NODEFILE=$(generate_pbs_nodefile)
        export NODEFILE
        cat "$NODEFILE" | uniq > machine.file.$JOBID
        echo -e "\nNodes allocated:\n================"
        echo $(cat machine.file.$JOBID | sed -e 's/\..*$//g')
fi

echo -e "\nnumtasks=$numtasks, numnodes=$numnodes, mpi_tasks_per_node=$mpi_tasks_per_node (OMP_NUM_THREADS=$OMP_NUM_THREADS)"

echo -e "\nExecuting command:\n==================\n$CMD\n"
eval "$CMD"
