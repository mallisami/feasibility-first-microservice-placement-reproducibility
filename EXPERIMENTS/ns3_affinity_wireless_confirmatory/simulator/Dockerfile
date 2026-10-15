FROM ns3-wigig:v0.5

COPY evaluate_bplus_affinity_dense.cc scratch/evaluate_bplus_affinity_dense.cc
RUN ./waf build -j2

CMD ["./waf", "--run-no-build", "evaluate_bplus_affinity_dense --PrintHelp"]
