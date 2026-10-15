FROM ns3-wigig:v0.5

COPY evaluate_shared_airtime_boundary.cc scratch/evaluate_shared_airtime_boundary.cc
RUN ./waf build -j2

CMD ["./waf", "--run-no-build", "evaluate_shared_airtime_boundary --PrintHelp"]
